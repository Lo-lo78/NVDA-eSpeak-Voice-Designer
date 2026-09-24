# NVDA eSpeak Voice Designer

eSpeak Voice Designer is an accessible real-time voice and variant editor for the eSpeak NG synthesizer included with NVDA.

Current version: **0.2.47**  
Current development build: **TEST49**  
Manifest compatibility: NVDA **2025.0.0** or later, tested through **2026.1.1**.

## What it does

The add-on lets you edit standard eSpeak voice and variant parameters while listening to the result directly through NVDA.

It provides a keyboard-oriented interface for:

- Voice pitch, pitch span, voicing, consonants, roughness, flutter, clarity, speed and echo.
- Formants 0-8.
- Breath and breath width controls.
- Tone frequency/amplitude points and higher-level tone macros.
- Klatt 6 / SpeechPlayer controls.
- Stress length, stress add and stress amplitude.
- Voice metadata.
- Advanced parser and MBROLA options.
- Personal variant creation, renaming and deletion.
- Previewing changes in real time.

Designer-only macros are converted to normal eSpeak directives when a voice is saved, so saved variants remain usable by eSpeak/NVDA without this add-on.

## Opening the Designer

Press:

`NVDA+Alt+V`

If another synthesizer is active, the add-on temporarily switches to eSpeak NG while the Designer is open and restores the previous synthesizer and voice when the Designer is closed.

## Important shortcuts

- `Alt+S`: Section.
- `Alt+V`: cycle between NVDA eSpeak variants and Saved variants.
- `Alt+L`: first parameter of the current section.
- `Alt+P`: preview.
- `Alt+E`: move to Preview text.
- `Alt+N`: move to Variant name.
- `Alt+H`: help.
- `Ctrl+S`: Save variant as.
- `Ctrl+Shift+S`: install a clean saved personal variant into NVDA's native eSpeak variants folder.
- `Ctrl+Delete`: restore the current editing base.
- `F2`: rename the selected saved personal variant.
- `Delete`: delete the selected saved personal variant after confirmation.

Numeric parameters can be changed with Arrow Up/Down and Page Up/Down, or typed directly.

## Drafts and personal variants

The Designer supports persistent drafts. A draft can survive NVDA and Windows restarts and is resumed when the Designer is opened again.

A native/factory eSpeak variant is treated as a starting source. To install an edited voice as a native-compatible variant, first save it as a personal variant with `Ctrl+S`.

A saved personal variant is considered clean until it is edited. The title shows `Modified` whenever unsaved changes are present.

Installation with `Ctrl+Shift+S` is non-destructive: an existing native variant is never overwritten. If the requested filename already exists, a numeric suffix is added.

## TEST49

Version 0.2.47 TEST49 refines the Modified/install workflow:

- A freshly loaded saved personal variant is clean and can be installed immediately.
- Native/factory eSpeak variants and the standard voice start as Modified and must first be saved as a personal variant.
- Editing a personal variant marks it Modified again until it is saved.
- Native installation remains non-destructive.
- After installation, the Designer remains on the clean personal source instead of switching to the installed native copy.

## Languages

Interface and documentation are included in:

- English
- Italian
- Spanish
- French

Unsupported interface languages fall back to English.

## Installation

Download the latest `.nvda-addon` file from the GitHub Releases page and open it while NVDA is running. Follow NVDA's installation prompts.

## Building from source

Python 3 is sufficient to package the add-on:

```text
python build.py
```

The generated package is written to:

```text
dist/eSpeakVoiceDesigner_0.2.47.nvda-addon
```

## Repository layout

```text
globalPlugins/espeakVoiceDesigner/   NVDA global plug-in source
locale/                              translations
doc/                                 localized documentation
manifest.ini                         NVDA add-on manifest
LOCALIZATION_GUIDE.txt               localization notes
build.py                             local package builder
.github/workflows/                   GitHub build/release automation
```
