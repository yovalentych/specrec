# V-1200 / ПЭ-5400В USB protocol

Worked out by experiment on 2026-10-28 (an instrument labelled
Mapada V-1200; it reports itself as **ПЭ-5400В**, the ЭКРОС rebrand). The vendor does not
publish it. The vendor PC programs (Mapada *M. Wave*, ЭКРОС *Экохим SC5400*) are
Windows-only and copy-protected.

## Link
- USB → Silicon Labs **CP2102N** USB-UART bridge (VID 0x10C4, PID 0xEA60).
  macOS has a built-in driver: the port is `/dev/cu.usbserial-*`.
- **19200 baud, 8N1**, no flow control.
- A text console: each command ends with `CR`. The instrument echoes the command plus
  `CR LF`, then sends the answer lines, each ending with `LF CR`, and finally `LF CR >`.
  Text is GB2312 (the model name has Cyrillic letters `ПЭ` encoded as `A7 B1 A7 BF`).
- An empty line gets `CR LF >`. An unknown command gets `Invalid Command.`, a known
  command with a bad argument gets `Bad Argument`.

## Commands
| Cmd | Answer | Meaning |
|---|---|---|
| `CO` | `ПЭ-5400B`, `540.0`, `0`, `0`, `3`, `1`, `0` | connect: model, current wavelength, 5 status values (meaning unknown) |
| `QU` | — | disconnect. Until the next `CO`, the commands below are accepted but silent |
| `SW <nm>` | — | go to wavelength (integer nm). ~2.4 s for a small step, up to ~15 s across the range |
| `BK` | dark, reference, gain | blank with auto gain, ~7 s. Also zeroes the instrument's display |
| `GE <n>` | n numbers | raw energy readings, 16-bit ADC (65535 = saturated), ~0.2 s for 10 |
| `GA` | gain index | 0..7 |
| `SA <n>` | — | set gain index n−1. Each step doubles the signal |
| `RD` | 8 numbers | stored dark readings for gains 0..7 (e.g. 5 12 28 60 124 254 509 1016) |
| `GD` | 8 numbers | re-measure the dark readings, ~12 s |
| `DI` `DO` `WI` `WO` `SL` | — | accepted, purpose unknown (not used) |

All two-letter commands A–Z were scanned. Some were skipped on purpose because they might
erase or recalibrate something: `CL CD CE ER DE DL DF FM FO RS RE RT CA IN IT DM WR WE FL FS
BT BO UP UD PG`. Longer commands were not explored.

## Measurement
Single beam:

    T = (E_sample − dark[g]) / (E_blank − dark[g]),   A = −log10 T

Both energies are taken at the same wavelength and the same gain `g`. For photometry and
kinetics, SpecRec uses the instrument's own `BK`. For spectra, it uses a faster blank of
its own at every wavelength (`quick_reference`). That blank picks a gain that keeps the
blank signal between 24 000 and 60 000, then averages `GE`.

Check on the real instrument: an empty cuvette holder against its own blank gave
|A| ≤ 0.0002.
