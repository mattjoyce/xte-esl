# XTE protocol specification

Version 1.1, 2026-09-07.

**Provenance.** This specification has two kinds of content and marks them.

- *Observed*: exercised on a Poshiji PSJ-213, hardware revision 2, firmware
  4.0.2, over BlueZ. Sections 4, 5, 6.1 (commands `01` short form and `04`),
  6.3 (the `01` and `04` replies with status `FF`), 7, 8.1 and 8.2 without
  patching.
- *Transcribed*: read from the vendor application's code and reproduced
  here faithfully, but never seen on a tag. Sections 6.2 beyond one batch,
  the `02` and `05` commands, the `02` and `68` replies, 6.4, 8.3 and 8.4.
  Each such section carries the line *Status: transcribed, not exercised.*

A port that implements only the observed parts puts an image on a PSJ-213.

This document is the only source a codec port needs. It is written in a
controlled style: short sentences, one instruction per sentence, one name
per thing. Terms in **bold** are defined in section 2 and used the same way
throughout.

## 1. Scope

This specification describes how a host sends an image to an XTE electronic
shelf label over Bluetooth Low Energy. It covers:

- the BLE transport
- the advertisement the tag broadcasts
- the three frame types
- the image container and pixel format
- the procedures for a push and for recovery from lost packets
- the panel geometry of the PSJ-213

It does not cover the base station, the cloud back end, firmware update
(OTA) beyond the command byte, or NFC.

## 2. Terms

| term | meaning |
|---|---|
| **tag** | the electronic shelf label. It is the BLE peripheral. |
| **host** | the device that sends the image. It is the BLE central. |
| **frame** | one logical message. A frame can span several BLE writes. |
| **command frame** | a frame from the host that tells the tag to do something |
| **data packet** | a frame from the host that carries up to 1211 bytes of the container |
| **response frame** | a frame from the tag, delivered as a BLE notification |
| **container** | the image payload, section 6. It starts with `XTEK`. |
| **write** | one BLE write-without-response. Maximum 244 bytes. |
| **batch** | up to 204800 bytes of the container, sent as one group of data packets. Only containers larger than that need more than one batch, section 8.4. |
| **checksum** | the sum of the listed bytes, modulo 256, unless a width is given |
| **panel** | the e-paper display inside the tag |
| **buffer** | the pixel array in the tag's native orientation, section 7 |

## 3. Conventions

- All multi-byte integers are big-endian.
- `u8`, `u16`, `u32` are unsigned integers of 1, 2 and 4 bytes.
- Byte offsets start at 0.
- Hex examples show one byte per pair, separated by spaces.
- `XTE` is the three ASCII bytes `58 54 45`. Every frame starts with it.

## 4. Transport

### 4.1 GATT

| item | value |
|---|---|
| service UUID | `00002760-08C2-11E1-9073-0E8AC72E1001` |
| write characteristic | `00002760-08C2-11E1-9073-0E8AC72E0001`, property write-without-response |
| notify characteristic | `00002760-08C2-11E1-9073-0E8AC72E0002`, property notify |

Select the write characteristic as the first characteristic in the service
with the `write` or `write-without-response` property. Select the notify
characteristic as the first characteristic with the `notify` or `indicate`
property. The UUIDs above are what the PSJ-213 exposes.

The tag has no pairing and no bonding. Connect openly.

### 4.2 MTU and writes

1. Request an MTU of 247 after connection.
2. Send each frame as consecutive writes of at most 244 bytes.
3. Wait 5 ms between writes.

The tag also accepts 20-byte writes at the default MTU of 23. The push is
slower but correct. On BlueZ the stack negotiates the MTU itself (517 was
observed); the host only has to keep each write at 244 bytes or fewer.

### 4.3 Timeouts

| wait for | timeout |
|---|---|
| response to any command frame | 5 s |
| a patch round (section 8.3) | 300 s, the vendor application's value. Transcribed, not exercised. |

If a timeout expires, disconnect and start again.

## 5. Advertisement

The tag advertises under manufacturer ID `0x5258`. It also advertises its
name, which is the BLE address as twelve upper-case hex digits in reverse
byte order. Example: address `9F:1D:00:0B:33:36`, name `36330B001D9F`.

The manufacturer data, including the two company-ID bytes, has this layout:

| offset | size | field | PSJ-213 value |
|---|---|---|---|
| 0 | 1 | `X` (`58`) | `58` |
| 1 | 1 | `T` (`54`) or `R` (`52`) | `52` |
| 2 | 1 | record type. One of `FD`, `FE`, `FC`, `04` | `FD` |
| 3 | 1 | hardware revision | `02` |
| 4 | 1 | firmware major (high nibble) and minor (low nibble) | `40` = 4.0 |
| 5 | 1 | firmware patch | `02` |
| 6 | 2 | **device number**, u16. Identifies the tag type. | `00 8C` = 140 |
| 8 | 1 | battery, percent | `63` = 99 |
| 9 | 1 | chip type (high nibble), transmit power (low nibble) | `06` |
| 10 | 5 | not used by the host | `01 02 FF FF 1C` |

Accept the advertisement only if byte 0 is `58`, byte 1 is `54` or `52`, and
byte 2 is one of the four record types.

The tag alternates this record with a two-byte payload `FF 01` under the
same company ID. The rule above rejects it. Ignore it.

The **device number** selects the pixel packing. Section 7.2 gives the rule.
The advertisement does not say which inks the panel has. That is in the
tag's NFC record (`BWRY`) and in the vendor's model table, not on the air.

## 6. Frames

### 6.1 Command frame

| offset | size | field |
|---|---|---|
| 0 | 3 | `XTE` |
| 3 | 1 | frame type, `01` |
| 4 | 1 | frame length in bytes, including this header |
| 5 | 1 | checksum of bytes 6 to end |
| 6 | 1 | command |
| 7 | n | payload, defined per command |

Commands:

| command | payload | length | purpose |
|---|---|---|---|
| `01` | `u32 totalSize` | 11 | allocate flash for a container of `totalSize` bytes. Use when the container is 204800 bytes or smaller. |
| `01` | `u32 totalSize`, `u32 offset`, `u32 length` | 19 | allocate flash for one batch. Use when the container is larger than 204800 bytes. Transcribed. |
| `02` | none | 7 | ask which data packets of the current batch arrived. Transcribed. |
| `04` | `00` | 8 | refresh the panel. Single screen. |
| `04` | `03 03` | 9 | refresh the panel. Tag with more than one screen. Transcribed. |
| `05` | none | 7 | apply the uploaded firmware. Send an extra `00` after the frame so the total is 8 bytes. Transcribed. |

Examples:

```
allocate 7724 bytes      58 54 45 01 0b 4b 01 00 00 1e 2c
allocate batch           58 54 45 01 13 ef 01 00 04 93 e0 00 03 20 00 00 01 73 e0
                         (total 300000, offset 204800, length 95200)
verify                   58 54 45 01 07 02 02
refresh, one screen      58 54 45 01 08 04 04 00
refresh, two screens     58 54 45 01 09 0a 04 03 03
apply firmware           58 54 45 01 07 05 05 00
```

### 6.2 Data packet

| offset | size | field |
|---|---|---|
| 0 | 3 | `XTE` |
| 3 | 1 | frame type, `02` |
| 4 | 2 | frame length, u16. Equals 9 + data length. |
| 6 | 1 | checksum of bytes 7 to end |
| 7 | 1 | total number of data packets in this batch |
| 8 | 1 | index of this packet, starting at 0 |
| 9 | n | data. Maximum 1211 bytes. |

Build the data packets of a batch as follows:

1. Divide the batch into pieces of 1211 bytes. The last piece can be shorter.
2. Number the pieces from 0.
3. Put the number of pieces in byte 7 of every packet.

A batch can contain at most 255 data packets.

Example: 5 data bytes `00 01 02 03 04`, packet 2 of 7:

```
58 54 45 02 00 0e 13 07 02 00 01 02 03 04
```

### 6.3 Response frame

The tag sends a response frame as one notification. The notification is
padded with `00` to 16 bytes.

| offset | size | field |
|---|---|---|
| 0 | 3 | `XTE` |
| 3 | 1 | frame type, `04` |
| 4 | 1 | frame length, excluding the padding |
| 5 | 1 | checksum of bytes 6 to (length - 1), inclusive |
| 6 | 1 | command this response answers |
| 7 | 1 | status |
| 8 | n | extra bytes, defined per command |

Responses:

| command | status | extra | meaning |
|---|---|---|---|
| `01` | `FF` | one byte, value not understood | flash allocated. Continue. |
| `01` | other | | allocation failed. Disconnect. |
| `02` | ignore | packet bitmap from byte 7 | see section 8.3. Transcribed. |
| `04`, `05` | `FF` | | refresh started. The push is complete. |
| `04`, `05` | `68` | packet bitmap from byte 8 | data packets are missing. See section 8.3. Transcribed. |
| `04`, `05` | other | | unknown result. Disconnect. |

Verify a response before you act on it: byte 3 is `04`, the length byte is
at least 8 and not more than the notification, and the checksum matches.
Treat a frame that fails any check as absent.

Ignore any notification shorter than 8 bytes. Ignore any notification that
does not start with `XTE`.

Examples observed on the PSJ-213:

```
after allocate    58 54 45 04 09 bd 01 ff bd 00 00 00 00 00 00 00
after refresh     58 54 45 04 08 03 04 ff 00 00 00 00 00 00 00 00
```

The `FF` after a refresh arrives about 60 ms after the command. It means
the tag has accepted the image and started the panel waveform. The panel
takes a further 15 to 25 seconds to settle.

### 6.4 Packet bitmap

Status: transcribed, not exercised.

The packet bitmap tells the host which data packets the tag received.

1. Read the bytes from the offset given in section 6.3 up to, but not including, the frame length byte's value. Do not read the padding.
2. Expand each byte into 8 bits, most significant bit first.
3. Bit `i` is data packet `i`. A `1` means received. A `0` means missing.
4. Use only the first `total` bits, where `total` is the packet count of the batch.
5. If the frame carries fewer than `total` bits, treat the packets without a bit as missing.

A 16-byte notification carries 8 bitmap bytes from offset 8, which covers
64 packets. A full batch has up to 170. Whether the tag then sends a longer
notification, or several, has not been observed.

## 7. Container

### 7.1 Layout

| offset | size | field |
|---|---|---|
| 0 | 4 | `XTEK` (`58 54 45 4B`) |
| 4 | 4 | checksum, u32. Sum of all bytes from offset 12 to the end. |
| 8 | 4 | total container length, u32 |
| 12 | 1 | image count, `N` |
| 13 | 4·N | offset of each image record, u32, from the start of the container |
| 13 + 4·N | | image records, one after another |

Image record:

| offset | size | field |
|---|---|---|
| 0 | 4 | x, u32 |
| 4 | 4 | y, u32 |
| 8 | 4 | width, u32 |
| 12 | 4 | height, u32 |
| 16 | 1 | compression. `00` raw, `01` RLE |
| 17 | 4 | data length, u32 |
| 21 | n | data |

A push of a full screen uses one image record at x 0, y 0.

Example: one 8x2 image, four packed bytes `55 55 55 55`, RLE chosen:

```
58 54 45 4b  00 00 00 cf  00 00 00 2a  01  00 00 00 11
00 00 00 00  00 00 00 00  00 00 00 08  00 00 00 02  01  00 00 00 04
02 55 02 55
```

### 7.2 Pixel packing, four colours (BWRY)

Map each source pixel to a two-bit code by exact RGB match:

| RGB | code | ink |
|---|---|---|
| `FF FF FF` | 1 | white |
| `FF FF 00` | 2 | yellow |
| `FF 00 00` | 3 | red |
| any other | 0 | black |

Quantise the image to these four colours before packing. Do not send
anti-aliased edges to the packer. It maps them to black.

Pack the codes as follows:

1. Take the pixels in row-major order.
2. Pad each row with code 0 to a multiple of 4 pixels.
3. Put 4 pixels in each byte. The first pixel goes in bits 7 and 6. The fourth pixel goes in bits 1 and 0.

Example: six pixels white, yellow, red, black, black, white:

```
codes  1 2 3 0 | 0 1 (0 0)
bytes  6c 10
```

This packing is verified for **device number** 140. The vendor code applies
it to every other four-colour tag except device numbers 97, 102, 106, 109,
119 and 122, which use a two-plane packing that is out of scope here. A port
must refuse a device number it does not know rather than guess.

### 7.3 RLE

RLE encodes the packed bytes. Do the following:

1. Split the packed bytes into a first half of `floor(n / 2)` bytes and a second half with the rest.
2. Encode each half separately.
3. In each half, replace every run of equal bytes with two bytes: the run length, then the value.
4. Limit the run length to 255. Split longer runs.
5. Concatenate the two encoded halves.

Example: `09 09 09 09 09 09 01 01`

```
first half   09 09 09 09         ->  04 09
second half  09 09 01 01         ->  02 09 02 01
result       04 09 02 09 02 01
```

Plain RLE over the whole input would give `06 09 02 01`. That is wrong.

Rules the example does not show:

- Splitting a long run is greedy. A run of 300 becomes `FF v 2D v`, never `96 v 96 v`.
- An empty half produces no bytes. A one-byte input has an empty first half and encodes as `01 v`.
- When the RLE output has exactly the raw length, use RLE.

Use RLE only if the result is not longer than the raw bytes. Otherwise send
raw with compression `00`. The tag accepts both.

## 8. Procedures

### 8.1 Prepare the image, PSJ-213

The PSJ-213 panel is 250 by 122 pixels as viewed. The tag stores the image
as a portrait **buffer** of 122 columns and 250 rows.

1. Draw the image in landscape, 250 wide, 122 high.
2. Quantise to the four colours.
3. Rotate the image 90 degrees counter-clockwise. The result is 122 wide and 250 high.
4. Pack the rotated image with width 122 and height 250. Each row is 31 bytes. The buffer is 7750 bytes.
5. Build the container with one image record, x 0, y 0, width 122, height 250.

"As viewed" means the orientation in which the factory test screen's text
(the MAC, `2.13 H:2 V:4.0.2 B:80%`) reads upright; the battery door is then
at the back and the NFC coil under the right half. Buffer row 0 is the
right-hand edge of the panel in that orientation. Pixel 0 of a row (bits 7
and 6 of byte 0) is the top edge. Do not flip the image vertically.

Do not send 63-byte rows (landscape) and do not pad the width to 128. Both
display as diagonal shear.

### 8.2 Push a container of 204800 bytes or fewer

1. Connect to the tag.
2. Request MTU 247.
3. Enable notifications on the notify characteristic.
4. Send command `01` with the container length.
5. Wait for the `01` response. If the status is not `FF`, disconnect.
6. Send all data packets in index order.
7. Wait 100 ms.
8. Send command `04` with payload `00`.
9. Wait for the `04` response.
10. If the status is `FF`, disconnect. The push is complete.
11. If the status is `68`, do the patch procedure in section 8.3, then go to step 7.

### 8.3 Patch missing packets

Status: transcribed, not exercised. No packet has been lost in any observed push.

1. Read the packet bitmap from the response, section 6.4.
2. If the bitmap shows nothing missing, the host and the tag disagree about the packet count. Disconnect and report failure.
3. Send every data packet whose bit is 0, in index order.
4. Wait 100 ms.
5. Send command `04` again and wait for the response.
6. Stop after 3 patch rounds. Disconnect and report failure.

### 8.4 Push a container larger than 204800 bytes

Status: transcribed, not exercised. The Python codec refuses such containers.

1. Divide the container into batches of 204800 bytes. The last batch can be shorter.
2. For each batch, in order:
   1. Send command `01` in the 19-byte form with the container length, the batch offset and the batch length.
   2. Wait for the `01` response with status `FF`.
   3. Send all data packets of the batch. The packet count and indexes restart at 0 for each batch.
   4. If this is the last batch, go to step 3.
   5. Send command `02`. Wait for the `02` response.
   6. If the bitmap shows missing packets, send them, then send `02` again. Stop after 3 rounds.
3. Wait 100 ms. Send command `04`. Handle the response as in section 8.2, steps 9 to 11.

No PSJ-213 image approaches this size. The procedure is given for larger
tags and for firmware upload.

## 9. Conformance

A codec port is correct when it reproduces every vector in
`testdata/reference.json` byte for byte. `testdata/README.md` describes the
fields and which vectors came from the vendor's encoder and which from this
project's. Do the conformance test before adding a BLE transport.

Every precondition failure in a port must surface as one error type of the
port's own, never as a language runtime error. The preconditions are: pixel
count equals width times height; packed data length equals
`ceil(width / 4) * height`; 1 to 255 images per container; container at most
204800 bytes for the single-batch procedure; every geometry field fits a u32.

## 10. Observed timings, PSJ-213

| step | time |
|---|---|
| scan and connect | 1.7 s |
| MTU 517 negotiated by BlueZ | included above |
| allocate to response | 90 ms |
| 4 data packets, 244-byte writes, 5 ms gap | 100 ms |
| refresh to `FF` | 60 ms |
| connect to `FF` | 2.5 s |
| panel settled | about 20 s after `FF` |
