package xte

import (
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"sync"
	"time"
)

// Transport represents one BLE connection, owned exclusively by an Uploader.
// Methods MUST return promptly when ctx expires, and must not leave writes or
// connections running after Disconnect returns. Callbacks may run concurrently.
// Connect enables notifications before returning. Write must not retain data.
type Transport interface {
	WriteSize() int // Negotiated payload size, 1–244; may change during Connect.
	Connect(ctx context.Context, notify func([]byte), disconnected func(error)) error
	Write(ctx context.Context, data []byte) error
	Disconnect(ctx context.Context) error
}

type UploadOptions struct {
	MultiScreen    bool
	CommandTimeout time.Duration  // Zero defaults to 5 seconds; also bounds I/O and cleanup.
	PatchTimeout   time.Duration  // Zero defaults to 300 seconds per recovery phase.
	WriteDelay     *time.Duration // Nil defaults to 5 ms; a pointer to zero disables pacing.
}

// Uploader serialises access to one transport. Use one Uploader per transport;
// simultaneous Upload calls fail without disturbing the active upload.
type Uploader struct {
	transport Transport
	mu        sync.Mutex
}

func NewUploader(transport Transport) (*Uploader, error) {
	if transport == nil {
		return nil, invalid("transport is nil")
	}
	return &Uploader{transport: transport}, nil
}

// Upload resolves when refresh is accepted, before the panel has settled.
// It disconnects after success, failure, or cancellation; it does not retry an
// entire upload. Do not modify container concurrently while this call snapshots it.
func (u *Uploader) Upload(ctx context.Context, container []byte, options UploadOptions) (err error) {
	if ctx == nil {
		return invalid("context is nil")
	}
	if u == nil || u.transport == nil {
		return invalid("uploader has no transport")
	}
	if !u.mu.TryLock() {
		return invalid("an upload is already using this transport")
	}
	defer u.mu.Unlock()
	if err = ctx.Err(); err != nil {
		return err
	}
	if len(container) < 13 || string(container[:4]) != "XTEK" || uint64(len(container)) > maxU32 || binary.BigEndian.Uint32(container[8:]) != uint32(len(container)) || binary.BigEndian.Uint32(container[4:]) != checksum(container[12:]) || container[12] == 0 || 13+4*int(container[12]) > len(container) {
		return invalid("expected an XTEK container with matching length and checksum")
	}
	timeout := options.CommandTimeout
	if timeout == 0 {
		timeout = 5 * time.Second
	}
	patchTimeout := options.PatchTimeout
	if patchTimeout == 0 {
		patchTimeout = 300 * time.Second
	}
	delay := 5 * time.Millisecond
	if options.WriteDelay != nil {
		delay = *options.WriteDelay
	}
	if timeout < 0 || patchTimeout < 0 || delay < 0 {
		return invalid("timeouts must be positive and write delay nonnegative")
	}
	if _, err = SplitWrites(nil, u.transport.WriteSize()); err != nil {
		return err
	}
	data := bytes.Clone(container)
	sessionCtx, cancel := context.WithCancelCause(ctx)
	defer cancel(nil)
	s := uploadSession{transport: u.transport, timeout: timeout, delay: delay}
	defer func() {
		cancel(errors.New("xte: upload session closed"))
		cleanupCtx, cleanupCancel := context.WithTimeout(context.Background(), timeout)
		defer cleanupCancel()
		cleanupErr := u.transport.Disconnect(cleanupCtx)
		if err == nil && cleanupErr != nil {
			err = fmt.Errorf("disconnect: %w", cleanupErr)
		}
	}()
	connectCtx, connectCancel := context.WithTimeout(sessionCtx, timeout)
	err = u.transport.Connect(connectCtx, s.notify, func(reason error) {
		if reason == nil {
			reason = errors.New("xte: BLE device disconnected")
		}
		cancel(reason)
	})
	connectCause := context.Cause(connectCtx)
	connectCancel()
	if connectCause != nil {
		return connectCause
	}
	if err != nil {
		return fmt.Errorf("connect: %w", err)
	}
	if err = context.Cause(sessionCtx); err != nil {
		return err
	}
	if _, err = SplitWrites(nil, u.transport.WriteSize()); err != nil {
		return err
	}
	refresh := Refresh(options.MultiScreen)
	for offset := 0; offset < len(data); {
		end := offset + min(BatchSize, len(data)-offset)
		batch := data[offset:end]
		var allocation []byte
		if len(data) > BatchSize {
			allocation, err = AllocateBatch(uint32(len(data)), uint32(offset), uint32(len(batch)))
		} else {
			allocation, err = Allocate(uint32(len(data)))
		}
		if err != nil {
			return err
		}
		reply, err := s.request(sessionCtx, allocation)
		if err != nil {
			return err
		}
		if reply.Status != 0xff {
			return fmt.Errorf("xte: allocation failed: status 0x%02x", reply.Status)
		}
		packets, err := DataPackets(batch)
		if err != nil {
			return err
		}
		for _, packet := range packets {
			if err = s.send(sessionCtx, packet); err != nil {
				return err
			}
		}
		final := end == len(data)
		frame := Verify()
		if final {
			if err = pause(sessionCtx, 100*time.Millisecond); err != nil {
				return err
			}
			frame = refresh
		}
		reply, err = s.request(sessionCtx, frame)
		if err != nil {
			return err
		}
		patchCtx, patchCancel := context.WithTimeout(sessionCtx, patchTimeout)
		err = s.recover(patchCtx, packets, reply, frame, final)
		patchCancel()
		if err != nil {
			return err
		}
		offset = end
	}
	return nil
}

type uploadSession struct {
	transport      Transport
	timeout, delay time.Duration
	mu             sync.Mutex
	pending        chan Response
	command        byte
}

func (s *uploadSession) notify(data []byte) {
	r, ok := ParseResponse(data)
	if !ok {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.pending != nil && r.Command == s.command {
		select {
		case s.pending <- r:
		default:
		} // First matching reply wins; never block BLE callbacks.
	}
}
func pause(ctx context.Context, d time.Duration) error {
	if err := context.Cause(ctx); err != nil {
		return err
	}
	if d == 0 {
		return nil
	}
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return context.Cause(ctx)
	case <-timer.C:
		return context.Cause(ctx)
	}
}
func (s *uploadSession) send(ctx context.Context, frame []byte) error {
	writes, err := SplitWrites(frame, s.transport.WriteSize())
	if err != nil {
		return err
	}
	for _, write := range writes {
		if err = context.Cause(ctx); err != nil {
			return err
		}
		writeCtx, cancel := context.WithTimeout(ctx, s.timeout)
		err = s.transport.Write(writeCtx, write)
		cause := context.Cause(writeCtx)
		cancel()
		if cause != nil {
			return cause
		}
		if err != nil {
			return fmt.Errorf("write: %w", err)
		}
		if err = pause(ctx, s.delay); err != nil {
			return err
		}
	}
	return nil
}
func (s *uploadSession) request(ctx context.Context, frame []byte) (Response, error) {
	requestCtx, cancel := context.WithTimeout(ctx, s.timeout)
	defer cancel()
	reply := make(chan Response, 1)
	s.mu.Lock()
	s.pending = reply
	s.command = frame[6]
	s.mu.Unlock()
	defer func() { s.mu.Lock(); s.pending = nil; s.mu.Unlock() }()
	if err := s.send(requestCtx, frame); err != nil {
		return Response{}, err
	}
	select {
	case <-requestCtx.Done():
		return Response{}, context.Cause(requestCtx)
	case response := <-reply:
		if err := context.Cause(requestCtx); err != nil {
			return Response{}, err
		}
		return response, nil
	}
}
func (s *uploadSession) recover(ctx context.Context, packets [][]byte, reply Response, frame []byte, final bool) error {
	for round := 0; ; round++ {
		if err := context.Cause(ctx); err != nil {
			return err
		}
		if final && reply.Status == 0xff {
			return nil
		}
		if final && reply.Status != 0x68 {
			return fmt.Errorf("xte: refresh failed: status 0x%02x", reply.Status)
		}
		missing, err := reply.MissingPackets(len(packets))
		if err != nil {
			return err
		}
		if len(missing) == 0 {
			if final {
				return errors.New("xte: refresh reports missing packets but bitmap is complete")
			}
			return nil
		}
		if round == 3 {
			return errors.New("xte: packets still missing after 3 patch rounds")
		}
		for _, index := range missing {
			if err = s.send(ctx, packets[index]); err != nil {
				return err
			}
		}
		if err = pause(ctx, 100*time.Millisecond); err != nil {
			return err
		}
		reply, err = s.request(ctx, frame)
		if err != nil {
			return err
		}
	}
}
