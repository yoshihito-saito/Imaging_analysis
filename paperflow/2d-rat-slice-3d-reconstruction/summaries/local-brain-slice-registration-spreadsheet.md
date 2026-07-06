# Local Google Drive Notes - Brain Slice Registration Spreadsheet

## Source

Google Drive spreadsheet: `Brain Slice Registration`
https://docs.google.com/spreadsheets/d/1K8hGOXA6HuamGQwQ_lmwX5robOQ7q6nKeZ3WJWWTCjA

## Library Status

- Google Drive/Paperpile: in Google Drive, viewed by user.
- Read status: inspected range `Atlas Registration Tools!A1:Z100`.

## One-Sentence Takeaway

The user's prior notes already compare the most relevant practical software
families and identify `brainreg`, `SHARP-Track`, `Histology`, `ABBA`, and
`Slice2Volume` as likely options.

## Method Notes Extracted

The spreadsheet compares tools across atlas support, missing-part handling,
multimodal/multichannel support, 2D-vs-3D and 3D-vs-3D registration modes,
export formats, installation, documentation, source code, and compatibility.

Important entries for this request:

- `brainreg`: supports atlases provided by BrainGlobe, uses NiftyReg, suitable
  for 3D-to-3D affine and warped registration, and integrates with napari and
  downstream BrainGlobe tools.
- `SHARP-Track` / `Histology`: aimed at histology slices and Allen CCF-style
  workflows.
- `ABBA`: Fiji/ImageJ workflow using Elastix and BigWarp, with forward/backward
  transforms and QuPath/ImageJ interoperability.
- `Slice2Volume`: supports arbitrary 3D volumes, uses BioFormats, and can handle
  affine/warped automated registration according to the notes.

## Relevance To This Repository

Very high as a practical shortlist. It supports a two-track recommendation:
BrainGlobe for 3D volume atlas registration, and slice-oriented tools for
serial-section atlas mapping if a dense stack is not available.

## Relevance Score

5/5 as local workflow context.
