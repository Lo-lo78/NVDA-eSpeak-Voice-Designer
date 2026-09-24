from __future__ import annotations

import base64
import copy
import ctypes
import json
import os
import re
import shutil
import threading
import time

import addonHandler
import globalPluginHandler
import globalVars
import gui
import languageHandler
import scriptHandler
import synthDriverHandler
import ui
import wx
from logHandler import log

addonHandler.initTranslation()


ADDON_TITLE = "eSpeak Voice Designer"
TEST_LABEL = "TEST49"
_DEFAULT_PREVIEW_TEXT = _("This is an eSpeak voice preview.")
_NEW_VARIANT_ID = "new"
_NEW_VARIANT_LABEL = _("New variant")
_EDITOR_SIDECAR_SUFFIX = ".editor.json"
_EDITOR_SIDECAR_VERSION = 2
_DRAFT_FILE_NAME = "draft.editor.json"
_DRAFT_VERSION = 1

# Legacy complete template used only as a convenient schema for every editor field.
# Native NVDA/eSpeak variants are loaded directly; personal variants live in the add-on library.
_SCHEMA_TEMPLATE = {
    "gender": "male",
    "age": 0,
    "pitchBase": 78,
    "pitchRange": 115,
    "voicing": 165,
    "consonantUnvoiced": 194,
    "consonantVoiced": 255,
    "roughness": 3,
    "flutter": 2,
    "clarity": 4,
    "echoDelay": 0,
    "echoAmp": 0,
    "speed": 100,
    "formants": [
        [95, 146, 100, 0],
        [98, 90, 100, 0],
        [103, 98, 100, 0],
        [100, 90, 100, 0],
        [100, 101, 100, 0],
        [110, 120, 100, 2123],
        [100, 100, 100, 1200],
        [32, 125, 80, 600],
        [34, 95, 30, 49],
    ],
    "breath": [20, 5, 2, 10, 5, 0, 27, 100],
    "breathw": [255, 255, 60, 180, 160, 255, 255, 255],
    "toneCount": 4,
    "tone": [[500, 210], [470, 70], [160, 155], [2985, 32], [3000, 32]],
    # Voice variants expose the Klatt source selector. TEST14 also presents a
    # linked Klatt panel for all standard variant controls that the native Klatt
    # and SpeechPlayer paths actually consume. Deep frame parameters remain in
    # compiled phondata and are not faked as writable global values.
    "klattSource": 0,
    "wordsOverride": False,
    "wordGap": 0,
    "vowelPause": 0,
    "intonation": 0,  # 0 = inherit from selected language
    "stressLengthOverride": False,
    "stressLength": [0, 0, 0, 0, 0, 0, 0, 0],
    "stressAddOverride": False,
    "stressAdd": [0, 0, 0, 0, 0, 0, 0, 0],
    "stressAmpOverride": False,
    "stressAmp": [16, 16, 20, 20, 20, 24, 24, 22],
    "stressRuleOverride": False,
    "stressRule": [0, 0, 0],
    "bracketsOverride": False,
    "brackets": 4,
    "bracketsAnnouncedOverride": False,
    "bracketsAnnounced": 2,
    "lowercaseSentence": False,
    "spellingStress": False,
    "phonemes": "",
    "dictionary": "",
    "dictrules": "",
    "stressOpt": "",
    "numbers": "",
    "tunes": "",
    "replacements": "",
    "dictMinOverride": False,
    "dictMin": 0,
    "internalOptions": {
        "apostrophe": [False, 0],
        "l_dieresis": [False, 0],
        "l_prefix": [False, 0],
        "l_regressive_v": [False, 0],
        "l_unpronouncable": [False, 0],
        "l_sonorant_min": [False, 0],
    },
    "fastOverride": False,
    "fastValue": 449,
    "mbrolaOverride": False,
    "mbrolaVoice": "",
    "mbrolaPhonemes": "",
    "mbrolaSampleRate": 16000,
    "maintainer": "",
    "status": "",
    "metaDescription": "",
    "metaVersion": "",
    "metaLicense": "",
    "metaContact": "",
    "variantsOverride": False,
    "variants": 4,
    "languagePriority": 5,
}


_STRESS_VISIBLE = [
    (0, _("0 Unstressed")),
    (1, _("1 Reduced")),
    (2, _("2 Secondary stress")),
    (3, _("3 Unstressed word")),
    (6, _("6 Primary stress")),
    (7, _("7 Stressed syllable")),
]

_KLATT_CHOICES = [
    (_("Standard eSpeak - formant synthesis, Klatt disabled"), 0),
    (_("Klatt 6 - SpeechPlayer"), 6),
]

# `clarity` is not a generic percentage. eSpeak maps 0..4 to the highest
# formant synthesized from the harmonic spectrum (F1..F5). Value 5 keeps F1-F5
# but switches to the alternative, squarer peak shape.
_CLARITY_CHOICES = [
    (_("0 - harmonics through F1, softer"), 0),
    (_("1 - harmonics through F2"), 1),
    (_("2 - harmonics through F3"), 2),
    (_("3 - harmonics through F4"), 3),
    (_("4 - harmonics through F5, standard shape"), 4),
    (_("5 - harmonics through F5, squarer peaks"), 5),
]

_INTONATION_CHOICES = [
    (_("From language"), 0),
    (_("1 - Default"), 1),
    (_("2 - Less intonation"), 2),
    (_("3 - Less intonation, no comma rise"), 3),
    (_("4 - Rise at end of sentence"), 4),
]

_STATUS_CHOICES = [
    (_("None"), ""),
    (_("Testing - in development"), "testing"),
    (_("Mature - stable"), "mature"),
]


# Neutral eSpeak NG values used only to display controls for attributes that a
# selected variant does not explicitly override.  Sparse serialization below
# guarantees that these values are NOT written unless the user changes them.
_DEFAULT_VALUES = copy.deepcopy(_SCHEMA_TEMPLATE)
_DEFAULT_VALUES.update({
    "gender": "male",
    "age": 0,
    "pitchBase": 80,
    "pitchRange": 118,
    "voicing": 100,
    "consonantUnvoiced": 90,
    "consonantVoiced": 100,
    "roughness": 2,
    "flutter": 2,
    "clarity": 4,
    "echoDelay": 0,
    "echoAmp": 0,
    "speed": 100,
    "formants": [
        [100, 102, 109, 0],
        [100, 100, 100, 0],
        [100, 94, 100, 0],
        [100, 91, 125, 0],
        [100, 78, 134, 0],
        [100, 78, 134, 0],
        [100, 100, 100, 0],
        [100, 100, 100, 0],
        [100, 100, 100, 0],
    ],
    "breath": [0, 0, 0, 0, 0, 0, 0, 0],
    "breathw": [200, 200, 400, 400, 400, 600, 600, 600],
    "toneCount": 4,
    "tone": [[600, 170], [1200, 135], [2000, 110], [3000, 110], [3000, 110]],
    "klattSource": 0,
    "extraLines": [],
})


def _dataRoot():
    return os.path.join(globalVars.appArgs.configPath, ADDON_TITLE)


def _variantDirectory():
    return os.path.join(_dataRoot(), "variants")


def _draftPath():
    """Persistent working draft used by OK/Enter across NVDA restarts."""
    return os.path.join(_dataRoot(), _DRAFT_FILE_NAME)


def _jsonSafe(value):
    if isinstance(value, set):
        return sorted(_jsonSafe(v) for v in value)
    if isinstance(value, dict):
        return {str(k): _jsonSafe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonSafe(v) for v in value]
    return value


def _readDraftState():
    path = _draftPath()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict) or int(payload.get("version", 0)) != _DRAFT_VERSION:
            return None
        state = payload.get("state")
        if not isinstance(state, dict):
            return None
        state = copy.deepcopy(state)
        if "baselinePresent" in state:
            state["baselinePresent"] = set(state.get("baselinePresent") or [])
        return state
    except Exception:
        log.debugWarning("eSpeak Voice Designer: unable to read persistent draft", exc_info=True)
        return None


def _writeDraftState(state):
    if not isinstance(state, dict):
        return
    try:
        os.makedirs(_dataRoot(), exist_ok=True)
        payload = {"version": _DRAFT_VERSION, "state": _jsonSafe(state)}
        _writeTextAtomic(_draftPath(), json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception:
        log.error("eSpeak Voice Designer: unable to save persistent draft", exc_info=True)


def _deleteDraftState():
    try:
        path = _draftPath()
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        log.debugWarning("eSpeak Voice Designer: unable to remove persistent draft", exc_info=True)


def _nativeVariantDirectory():
    """Return NVDA's real eSpeak directory for language-independent variants.

    TEST36 removed the old copied-native cache, but this resolver is still
    required to read and install the real files in espeak-ng-data/voices/!v.
    It never copies variants into the add-on data directory.
    """
    candidates = [
        os.path.join(globalVars.appDir, "synthDrivers", "espeak-ng-data", "voices", "!v"),
    ]
    try:
        from synthDrivers import _espeak
        candidates.append(os.path.join(os.path.dirname(_espeak.__file__), "espeak-ng-data", "voices", "!v"))
    except Exception:
        pass
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return None

def _legacyStockVariantDirectory():
    """Location used by TEST5-TEST35 for copied native variants.

    TEST36 no longer reads from this cache. Native variants are enumerated and
    loaded directly through NVDA/eSpeak.
    """
    return os.path.join(_variantDirectory(), "_espeak")


def _removeLegacyStockVariantCache():
    """Best-effort removal of the obsolete copied-native-variant cache."""
    path = _legacyStockVariantDirectory()
    if not os.path.isdir(path):
        return
    try:
        shutil.rmtree(path)
    except Exception:
        log.debugWarning("eSpeak Voice Designer: unable to remove obsolete native-variant cache", exc_info=True)


def _nativeVariantPath(variantId):
    if not variantId or str(variantId).casefold() == "none":
        return None
    root = _nativeVariantDirectory()
    if not root:
        return None
    path = os.path.join(root, str(variantId))
    return path if os.path.isfile(path) else None


def _refreshNvdaVariantCache(synth=None):
    """Refresh NVDA's eSpeak variant dictionary after installing a new file."""
    synth = synth or synthDriverHandler.getSynth()
    if synth is None or getattr(synth, "name", "") != "espeak":
        return
    try:
        from synthDrivers import _espeak
        synth._variantDict = _espeak.getVariantDict()
        if hasattr(synth, "_availableVariants"):
            delattr(synth, "_availableVariants")
    except Exception:
        log.debugWarning("eSpeak Voice Designer: unable to refresh NVDA variant cache", exc_info=True)


def _setNativeVoiceAndVariantNow(voice, variant):
    """Load an installed NVDA/eSpeak voice+variant directly and synchronously.

    This bypasses the Designer runtime file completely. It is used whenever the
    user chooses an item from the NVDA eSpeak variants selector, guaranteeing
    that the clean native variant is heard regardless of the voice that was
    active when the Designer opened.
    """
    synth = synthDriverHandler.getSynth()
    if synth is None or getattr(synth, "name", "") != "espeak":
        raise RuntimeError(_("The current synthesizer is not eSpeak NG."))
    voice = _cleanSingleToken(voice) or "en"
    variant = str(variant or "none")
    try:
        synth.cancel()
    except Exception:
        log.debugWarning("eSpeak Voice Designer: unable to cancel speech before native variant load", exc_info=True)
    try:
        from synthDrivers import _espeak
        # Do not use NVDA's private _setVoiceAndVariant here: that helper
        # deliberately catches a failed variant load and silently falls back
        # to the base voice. An editor must instead know whether the requested
        # source variant really loaded.
        dll = getattr(_espeak, "espeakDLL", None)
        if dll is None or not hasattr(dll, "espeak_SetVoiceByName"):
            raise RuntimeError(_("This eSpeak build does not expose espeak_SetVoiceByName."))
        target = voice if variant.casefold() == "none" else f"{voice}+{variant}"
        func = dll.espeak_SetVoiceByName
        try:
            func.argtypes = (ctypes.c_char_p,)
            func.restype = ctypes.c_int
        except Exception:
            pass
        result = int(func(target.encode("utf-8")))
        if result != 0:
            raise RuntimeError(_("espeak_SetVoiceByName returned code {code}").format(code=result))
        # Keep NVDA's Python-side state coherent with the direct eSpeak call.
        try:
            synth._voice = voice
            synth._variant = variant
            info = getattr(synth, "availableVoices", {}).get(voice)
            if info is not None and getattr(info, "language", None):
                synth._language = info.language
        except Exception:
            log.debugWarning("eSpeak Voice Designer: unable to mirror native voice state into NVDA", exc_info=True)
    except Exception:
        log.error("eSpeak Voice Designer: direct native variant load failed", exc_info=True)
        raise



def _nativeVariantInstallDirectory():
    """Return the native eSpeak directory for language-independent variants."""
    return _nativeVariantDirectory()


def _elevatedCopyFile(sourcePath, destinationPath, callback):
    """Copy a file with UAC elevation and report completion through callback.

    callback receives (success: bool, errorText: str | None).
    """
    if os.name != "nt":
        callback(False, _("Elevated installation is available only on Windows."))
        return

    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_HIDE = 0
    INFINITE = 0xFFFFFFFF

    def psLiteral(text):
        return "'" + str(text).replace("'", "''") + "'"

    command = (
        "$ErrorActionPreference='Stop'; "
        f"Copy-Item -LiteralPath {psLiteral(sourcePath)} "
        f"-Destination {psLiteral(destinationPath)} -Force"
    )
    encodedCommand = base64.b64encode(command.encode("utf-16le")).decode("ascii")

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.hwnd = None
    info.lpVerb = "runas"
    info.lpFile = "powershell.exe"
    info.lpParameters = f"-NoProfile -NonInteractive -EncodedCommand {encodedCommand}"
    info.lpDirectory = os.path.dirname(sourcePath) or None
    info.nShow = SW_HIDE

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = (ctypes.POINTER(SHELLEXECUTEINFOW),)
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        # 1223 = ERROR_CANCELLED, normally UAC was cancelled by the user.
        if err == 1223:
            callback(False, _("Installation cancelled."))
        else:
            callback(False, _("Unable to start elevated installation (error {err}).").format(err=err))
        return

    processHandle = info.hProcess

    def waitForCopy():
        exitCode = wintypes.DWORD(1)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        try:
            kernel32.WaitForSingleObject(processHandle, INFINITE)
            kernel32.GetExitCodeProcess(processHandle, ctypes.byref(exitCode))
        finally:
            try:
                kernel32.CloseHandle(processHandle)
            except Exception:
                pass
        success = int(exitCode.value) == 0
        wx.CallAfter(
            callback,
            success,
            None if success else _("Elevated copy returned exit code {code}.").format(code=int(exitCode.value)),
        )

    threading.Thread(target=waitForCopy, name="eSpeakVoiceDesignerInstall", daemon=True).start()



def _backupNativeVariant(path):
    """Keep a private backup before replacing an existing native variant."""
    if not path or not os.path.isfile(path):
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backupDir = os.path.join(_dataRoot(), "native-backups", stamp)
    os.makedirs(backupDir, exist_ok=True)
    backupPath = os.path.join(backupDir, os.path.basename(path))
    suffix = 2
    while os.path.exists(backupPath):
        backupPath = os.path.join(backupDir, f"{os.path.basename(path)}.{suffix}")
        suffix += 1
    shutil.copy2(path, backupPath)
    return backupPath

def _runtimeVoicePath():
    # Legacy full-voice runtime used only when editing the standard voice.
    # Real source variants use _runtimeVariantLocation() + SetVoiceByName so
    # eSpeak applies them through LoadVoice(..., control=2).
    return os.path.join(globalVars.appArgs.configPath, "_esvdw")


_RUNTIME_VARIANT_LOCATION = None

def _runtimeVariantCandidatePaths():
    """Short writable files that can be reached from voices/!v by a variant name.

    eSpeak stores the complete ``!v/<variant>`` name in a 40-byte internal
    buffer, so the relative path must stay very short.  NVDA normally lives on
    the same system drive as Public/Windows.  The file itself remains outside
    Program Files and therefore needs no elevation for live edits.
    """
    out = []
    public = os.environ.get("PUBLIC")
    if public:
        out.append(os.path.join(public, "_e"))
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windir:
        out.append(os.path.join(windir, "Temp", "_e"))
    # This usually exceeds eSpeak's tiny variant-name buffer, but on portable
    # or unusually short configurations it is a useful no-UAC fallback.
    out.append(os.path.join(globalVars.appArgs.configPath, "_e"))
    seen = set()
    result = []
    for path in out:
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _runtimeVariantLocation():
    """Return ``(absoluteFile, variantSuffix)`` for a true runtime !v variant.

    ``variantSuffix`` may contain ``..`` components. eSpeak prefixes it with
    ``voices/!v/`` and opens the normalized path, but still loads the file with
    variant control=2.  Keep the resulting internal ``!v/<suffix>`` below the
    40-byte limit used by ExtractVoiceVariantName.
    """
    global _RUNTIME_VARIANT_LOCATION
    if _RUNTIME_VARIANT_LOCATION is not None:
        return _RUNTIME_VARIANT_LOCATION
    nativeDir = _nativeVariantDirectory()
    if not nativeDir:
        raise RuntimeError(_("NVDA's native eSpeak variants folder could not be found."))
    for path in _runtimeVariantCandidatePaths():
        try:
            relative = os.path.relpath(os.path.abspath(path), os.path.abspath(nativeDir))
        except (OSError, ValueError):
            continue
        # eSpeak's static variant_name[40] must hold '!v\' + relative + NUL.
        internal = "!v" + os.sep + relative
        try:
            if len(os.fsencode(internal)) >= 40:
                continue
        except Exception:
            if len(internal) >= 40:
                continue
        # SetVoiceByName also uses a 60-byte buffer for voice+variant. Leave
        # enough headroom for normal language identifiers.
        try:
            if len(os.fsencode(relative)) > 36:
                continue
        except Exception:
            if len(relative) > 36:
                continue
        parent = os.path.dirname(path)
        try:
            os.makedirs(parent, exist_ok=True)
            probe = path + ".probe." + str(os.getpid())
            with open(probe, "w", encoding="ascii") as f:
                f.write("ok")
            os.remove(probe)
        except Exception:
            try:
                if os.path.isfile(probe):
                    os.remove(probe)
            except Exception:
                pass
            continue
        _RUNTIME_VARIANT_LOCATION = (path, relative)
        return _RUNTIME_VARIANT_LOCATION
    raise RuntimeError(_("No short writable path is available for the live eSpeak variant."))


def _discardRuntimeVariantFile():
    paths = []
    if _RUNTIME_VARIANT_LOCATION is not None:
        paths.append(_RUNTIME_VARIANT_LOCATION[0])
    paths.extend(_runtimeVariantCandidatePaths())
    seen = set()
    for path in paths:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            log.debugWarning("eSpeak Voice Designer: unable to remove runtime variant", exc_info=True)


def _runtimeBaseVoice(path, fallback="en"):
    """Read the base language identifier from a Voice Designer runtime voice."""
    if not path or not os.path.isfile(path):
        return str(fallback or "en")
    text = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                text = f.read()
            break
        except UnicodeDecodeError:
            continue
        except Exception:
            return str(fallback or "en")
    for raw in (text or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0].casefold() == "language" and parts[1].casefold() != "variant":
            return parts[1]
    return str(fallback or "en")


def _discardRuntimeVoiceFile():
    try:
        path = _runtimeVoicePath()
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        log.debugWarning("eSpeak Voice Designer: unable to remove runtime voice", exc_info=True)
    _discardRuntimeVariantFile()


def _safeFileName(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip().strip(".")
    name = re.sub(r"\s+", " ", name).strip()
    return name or "variant"


def _availableNativeVariantFileName(targetDir, requestedFileName):
    """Return a non-existing filename so native eSpeak variants are never overwritten."""
    requestedFileName = _safeFileName(requestedFileName)
    candidate = requestedFileName
    if not os.path.exists(os.path.join(targetDir, candidate)):
        return candidate
    stem, extension = os.path.splitext(requestedFileName)
    # eSpeak !v files normally have no extension.  Keep an extension, if one
    # was intentionally used, and append the number to the visible base name.
    number = 2
    while True:
        candidate = f"{stem}{number}{extension}"
        if not os.path.exists(os.path.join(targetDir, candidate)):
            return candidate
        number += 1


def _cleanSingleToken(text):
    return str(text or "").strip().replace("\\", "-").replace("/", "-").split()[0] if str(text or "").strip() else ""


def _parseIntList(text, minimum=0, maximum=63):
    out = []
    for token in re.split(r"[\s,;]+", str(text or "").strip()):
        if not token:
            continue
        try:
            value = int(token)
        except ValueError:
            continue
        if minimum <= value <= maximum:
            out.append(value)
    return out


def _normalizeRawLines(text, keyword=None):
    lines = []
    for raw in str(text or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if keyword and not line.lower().startswith(keyword.lower() + " "):
            line = keyword + " " + line
        lines.append(line)
    return lines


def _ints(text):
    out = []
    for token in str(text or "").split():
        try:
            out.append(int(token))
        except Exception:
            break
    return out


def _readVariantFile(path):
    values = copy.deepcopy(_DEFAULT_VALUES)
    present = set()
    displayName = os.path.basename(path) if path else "none"
    replacements = []
    extraLines = []
    if not path or not os.path.isfile(path):
        values["extraLines"] = []
        return values, present, displayName

    text = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                text = f.read()
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        with open(path, "r", encoding="latin-1", errors="replace") as f:
            text = f.read()

    internalKeys = set(values.get("internalOptions", {}).keys())
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("//"):
            comment = line[2:].strip()
            lowerComment = comment.casefold()
            metadataComments = {
                "description:": "metaDescription",
                "voice-version:": "metaVersion",
                "license:": "metaLicense",
                "contact:": "metaContact",
            }
            matchedMetadata = False
            for prefix, field in metadataComments.items():
                if lowerComment.startswith(prefix):
                    values[field] = comment[len(prefix):].strip()
                    present.add(field)
                    matchedMetadata = True
                    break
            if matchedMetadata:
                continue
            continue
        if line.startswith("#"):
            continue
        parts = line.split(None, 1)
        key = parts[0]
        low = key.lower()
        rest = parts[1].strip() if len(parts) > 1 else ""
        nums = _ints(rest)
        try:
            if low == "language":
                continue
            elif low == "name":
                displayName = rest or displayName
            elif low == "gender":
                toks = rest.split()
                if toks:
                    values["gender"] = toks[0].lower() if toks[0].lower() in ("male", "female", "unknown") else values["gender"]
                if len(toks) > 1:
                    try: values["age"] = int(toks[1])
                    except Exception: pass
                present.add("gender")
            elif low == "formant" and len(nums) >= 2:
                idx = nums[0]
                if 0 <= idx < 9:
                    # Match eSpeak VoiceFormant exactly for omitted fields:
                    # freq=100, height=100, width=100, freqadd=0.
                    vals = [100, 100, 100, 0]
                    supplied = nums[1:5]
                    vals[:len(supplied)] = supplied
                    values["formants"][idx] = vals
                    present.add(f"formant:{idx}")
            elif low == "pitch" and len(nums) >= 2:
                values["pitchBase"], values["pitchRange"] = nums[:2]; present.add("pitch")
            elif low == "voicing" and nums:
                values["voicing"] = nums[0]; present.add("voicing")
            elif low == "consonants" and nums:
                values["consonantUnvoiced"] = nums[0]
                if len(nums) > 1: values["consonantVoiced"] = nums[1]
                present.add("consonants")
            elif low == "roughness" and nums:
                values["roughness"] = nums[0]; present.add("roughness")
            elif low == "flutter" and nums:
                values["flutter"] = nums[0]; present.add("flutter")
            elif low in ("clarity", "formantshape") and nums:
                values["clarity"] = nums[0]; present.add("clarity")
            elif low == "echo" and nums:
                values["echoDelay"] = nums[0]
                values["echoAmp"] = nums[1] if len(nums) > 1 else 0
                present.add("echo")
            elif low == "speed" and nums:
                values["speed"] = nums[0]; present.add("speed")
            elif low == "breath" and nums:
                # eSpeak Read8Numbers clears all eight values before sscanf.
                values["breath"] = (nums[:8] + [0] * 8)[:8]
                present.add("breath")
            elif low == "breathw" and nums:
                # A present abbreviated breathw directive also zero-fills its
                # omitted values; it does not inherit VoiceReset widths.
                values["breathw"] = (nums[:8] + [0] * 8)[:8]
                present.add("breathw")
            elif low == "tone" and len(nums) >= 2:
                pairs = []
                for i in range(0, min(len(nums), 10) - 1, 2):
                    pairs.append([nums[i], nums[i + 1]])
                if pairs:
                    values["toneCount"] = min(5, len(pairs))
                    while len(pairs) < 5:
                        pairs.append(copy.deepcopy(pairs[-1]))
                    values["tone"] = pairs[:5]
                    present.add("tone")
            elif low == "klatt" and nums:
                values["klattSource"] = nums[0]; present.add("klatt")
            elif low == "words" and nums:
                values["wordsOverride"] = True
                values["wordGap"] = nums[0]
                values["vowelPause"] = nums[1] if len(nums) > 1 else 0
                present.add("words")
            elif low == "intonation" and nums:
                values["intonation"] = nums[0]; present.add("intonation")
            elif low == "stresslength" and nums:
                values["stressLengthOverride"] = True
                values["stressLength"] = (nums[:8] + [0] * 8)[:8]
                present.add("stressLength")
            elif low == "stressadd" and nums:
                values["stressAddOverride"] = True
                values["stressAdd"] = (nums[:8] + [0] * 8)[:8]
                present.add("stressAdd")
            elif low == "stressamp" and nums:
                values["stressAmpOverride"] = True
                base = list(values["stressAmp"])
                base[:min(8, len(nums))] = nums[:8]
                values["stressAmp"] = base
                present.add("stressAmp")
            elif low == "stressrule" and nums:
                values["stressRuleOverride"] = True
                values["stressRule"] = (nums[:3] + [0] * 3)[:3]
                present.add("stressRule")
            elif low == "brackets" and nums:
                values["bracketsOverride"] = True; values["brackets"] = nums[0]; present.add("brackets")
            elif low == "bracketsannounced" and nums:
                values["bracketsAnnouncedOverride"] = True; values["bracketsAnnounced"] = nums[0]; present.add("bracketsAnnounced")
            elif low == "lowercasesentence":
                values["lowercaseSentence"] = True; present.add("lowercaseSentence")
            elif low == "spellingstress":
                values["spellingStress"] = True; present.add("spellingStress")
            elif low == "phonemes":
                values["phonemes"] = rest; present.add("phonemes")
            elif low == "dictionary":
                values["dictionary"] = rest; present.add("dictionary")
            elif low == "dictrules":
                values["dictrules"] = rest; present.add("dictrules")
            elif low == "stressopt":
                values["stressOpt"] = rest; present.add("stressOpt")
            elif low == "numbers":
                values["numbers"] = rest; present.add("numbers")
            elif low == "tunes":
                values["tunes"] = rest; present.add("tunes")
            elif low in ("dict_min", "dictmin") and nums:
                values["dictMinOverride"] = True; values["dictMin"] = nums[0]; present.add("dictMin")
            elif low == "replace":
                replacements.append(rest); present.add("replace")
            elif low in internalKeys and nums:
                values["internalOptions"][low] = [True, nums[0]]; present.add(low)
            elif low == "fast_test2" and nums:
                values["fastOverride"] = True; values["fastValue"] = nums[0]; present.add("fast")
            elif low == "mbrola":
                toks = rest.split()
                if toks:
                    values["mbrolaOverride"] = True
                    values["mbrolaVoice"] = toks[0]
                    if len(toks) >= 3:
                        values["mbrolaPhonemes"] = toks[1]
                        try: values["mbrolaSampleRate"] = int(toks[2])
                        except Exception: pass
                    elif len(toks) == 2:
                        try: values["mbrolaSampleRate"] = int(toks[1])
                        except Exception: values["mbrolaPhonemes"] = toks[1]
                    present.add("mbrola")
            elif low == "maintainer":
                values["maintainer"] = rest; present.add("maintainer")
            elif low == "status":
                values["status"] = rest; present.add("status")
            elif low == "variants" and nums:
                values["variantsOverride"] = True; values["variants"] = nums[0]; present.add("variants")
            else:
                extraLines.append(line)
        except Exception:
            log.debugWarning(f"eSpeak Voice Designer: unable to parse line in {path}: {line}", exc_info=True)
            extraLines.append(line)
    values["replacements"] = "\n".join(replacements)
    values["extraLines"] = extraLines
    return values, present, displayName



_LANGUAGE_FILE_INDEX = None


def _nativeDataRoot():
    variantDir = _nativeVariantDirectory()
    if variantDir:
        return os.path.dirname(os.path.dirname(variantDir))
    return None


def _buildLanguageFileIndex():
    """Index native eSpeak language files by identifier, relative path and basename."""
    global _LANGUAGE_FILE_INDEX
    if _LANGUAGE_FILE_INDEX is not None:
        return _LANGUAGE_FILE_INDEX
    index = {}
    dataRoot = _nativeDataRoot()
    langRoot = os.path.join(dataRoot, "lang") if dataRoot else None
    if not langRoot or not os.path.isdir(langRoot):
        _LANGUAGE_FILE_INDEX = index
        return index
    for root, _dirs, files in os.walk(langRoot):
        for fileName in files:
            path = os.path.join(root, fileName)
            rel = os.path.relpath(path, langRoot).replace(os.sep, "/")
            candidates = {rel.casefold(), fileName.casefold()}
            try:
                text = None
                for enc in ("utf-8-sig", "utf-8", "latin-1"):
                    try:
                        with open(path, "r", encoding=enc) as f:
                            text = f.read()
                        break
                    except UnicodeDecodeError:
                        continue
                for raw in (text or "").replace("\r", "").split("\n"):
                    line = raw.strip()
                    if not line or line.startswith("//") or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].casefold() == "language":
                        candidates.add(parts[1].casefold())
            except Exception:
                pass
            for key in candidates:
                index.setdefault(key, path)
    _LANGUAGE_FILE_INDEX = index
    return index


def _languageFileForVoice(identifier):
    ident = str(identifier or "").strip().replace("\\", "/")
    if not ident:
        return None
    index = _buildLanguageFileIndex()
    key = ident.casefold()
    if key in index:
        return index[key]
    base = key.rsplit("/", 1)[-1]
    return index.get(base)


def _overlayValues(baseValues, overlayValues, present):
    """Apply only directives explicitly present in overlayValues to baseValues."""
    out = copy.deepcopy(baseValues)
    present = set(present or ())
    scalarMap = {
        "voicing": "voicing", "roughness": "roughness", "flutter": "flutter",
        "clarity": "clarity", "speed": "speed", "intonation": "intonation",
        "brackets": "brackets", "bracketsAnnounced": "bracketsAnnounced",
        "lowercaseSentence": "lowercaseSentence", "spellingStress": "spellingStress",
        "phonemes": "phonemes", "dictionary": "dictionary", "dictrules": "dictrules",
        "stressOpt": "stressOpt", "numbers": "numbers", "tunes": "tunes",
        "dictMin": "dictMin", "maintainer": "maintainer", "status": "status",
        "metaDescription": "metaDescription", "metaVersion": "metaVersion",
        "metaLicense": "metaLicense", "metaContact": "metaContact",
        "variants": "variants",
    }
    if "gender" in present:
        out["gender"] = overlayValues.get("gender", out.get("gender"))
        out["age"] = overlayValues.get("age", out.get("age"))
    if "pitch" in present:
        out["pitchBase"] = overlayValues.get("pitchBase", out.get("pitchBase"))
        out["pitchRange"] = overlayValues.get("pitchRange", out.get("pitchRange"))
    if "consonants" in present:
        out["consonantUnvoiced"] = overlayValues.get("consonantUnvoiced", out.get("consonantUnvoiced"))
        out["consonantVoiced"] = overlayValues.get("consonantVoiced", out.get("consonantVoiced"))
    if "echo" in present:
        out["echoDelay"] = overlayValues.get("echoDelay", out.get("echoDelay"))
        out["echoAmp"] = overlayValues.get("echoAmp", out.get("echoAmp"))
    if "words" in present:
        out["wordGap"] = overlayValues.get("wordGap", out.get("wordGap"))
        out["vowelPause"] = overlayValues.get("vowelPause", out.get("vowelPause"))
    for key in ("breath", "breathw", "stressLength", "stressAdd", "stressAmp", "stressRule"):
        if key in present:
            out[key] = copy.deepcopy(overlayValues.get(key, out.get(key)))
    if "tone" in present:
        out["toneCount"] = overlayValues.get("toneCount", out.get("toneCount"))
        out["tone"] = copy.deepcopy(overlayValues.get("tone", out.get("tone")))
    if "klatt" in present:
        out["klattSource"] = overlayValues.get("klattSource", out.get("klattSource"))
    if "replace" in present:
        out["replacements"] = overlayValues.get("replacements", "")
    if "fast" in present:
        out["fastValue"] = overlayValues.get("fastValue", out.get("fastValue"))
    if "mbrola" in present:
        out["mbrolaVoice"] = overlayValues.get("mbrolaVoice", "")
        out["mbrolaPhonemes"] = overlayValues.get("mbrolaPhonemes", "")
        out["mbrolaSampleRate"] = overlayValues.get("mbrolaSampleRate", 16000)
    for i in range(9):
        key = f"formant:{i}"
        if key in present:
            out["formants"][i] = copy.deepcopy(overlayValues["formants"][i])
    internal = out.setdefault("internalOptions", {})
    for key in list(internal.keys()):
        if key in present:
            internal[key] = copy.deepcopy(overlayValues.get("internalOptions", {}).get(key, internal[key]))
    for key, field in scalarMap.items():
        if key in present:
            out[field] = copy.deepcopy(overlayValues.get(field, out.get(field)))
    # Keep compatibility booleans in sync for old saved files, even though TEST11
    # no longer exposes separate "Overwrite" check boxes in the normal UI.
    out["wordsOverride"] = "words" in present
    out["stressLengthOverride"] = "stressLength" in present
    out["stressAddOverride"] = "stressAdd" in present
    out["stressAmpOverride"] = "stressAmp" in present
    out["stressRuleOverride"] = "stressRule" in present
    out["bracketsOverride"] = "brackets" in present
    out["bracketsAnnouncedOverride"] = "bracketsAnnounced" in present
    out["dictMinOverride"] = "dictMin" in present
    out["fastOverride"] = "fast" in present
    out["mbrolaOverride"] = "mbrola" in present
    out["variantsOverride"] = "variants" in present
    extras = list(baseValues.get("extraLines", []) or [])
    extras.extend(list(overlayValues.get("extraLines", []) or []))
    out["extraLines"] = extras
    return out


# Voice-quality state that eSpeak resets before applying a `language variant`
# file (LoadVoice(..., control=2)).  A native !v variant therefore does NOT
# inherit these timbral values from the language voice; missing values come
# from VoiceReset instead.  Language/prosody options continue to come from the
# selected language and are deliberately left out of this set.
_VARIANT_RESET_DIRECTIVES = {
    "pitch", "voicing", "consonants", "roughness", "flutter", "clarity",
    "echo", "speed", "breath", "breathw", "tone", "klatt", "fast",
}
_VARIANT_RESET_DIRECTIVES.update(f"formant:{i}" for i in range(9))


def _variantResetBase(languageValues):
    """Return the effective state immediately after eSpeak VoiceReset(2).

    Keep language/prosody/parser settings from the selected language, but reset
    the timbral voice fields exactly as a real !v variant load does before the
    variant file is parsed.
    """
    out = copy.deepcopy(languageValues)
    defaults = _DEFAULT_VALUES
    for field in (
        "pitchBase", "pitchRange", "voicing", "consonantUnvoiced",
        "consonantVoiced", "roughness", "flutter", "clarity", "echoDelay",
        "echoAmp", "speed", "klattSource", "fastValue",
    ):
        out[field] = copy.deepcopy(defaults[field])
    out["formants"] = copy.deepcopy(defaults["formants"])
    out["breath"] = copy.deepcopy(defaults["breath"])
    out["breathw"] = copy.deepcopy(defaults["breathw"])
    out["toneCount"] = defaults["toneCount"]
    out["tone"] = copy.deepcopy(defaults["tone"])
    out["fastOverride"] = False
    return out


def _readVoiceText(path):
    if not path or not os.path.isfile(path):
        return ""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except Exception:
            return ""
    try:
        with open(path, "r", encoding="latin-1", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def _directiveKeyFromLine(raw):
    """Map one standard eSpeak source line to the Designer directive key."""
    line = str(raw or "").strip()
    if not line:
        return None
    if line.startswith("//"):
        comment = line[2:].strip().casefold()
        for prefix, key in (
            ("description:", "metaDescription"),
            ("voice-version:", "metaVersion"),
            ("license:", "metaLicense"),
            ("contact:", "metaContact"),
        ):
            if comment.startswith(prefix):
                return key
        return None
    if line.startswith("#"):
        return None
    parts = line.split(None, 1)
    low = parts[0].casefold()
    rest = parts[1] if len(parts) > 1 else ""
    if low == "formant":
        nums = _ints(rest)
        if nums and 0 <= nums[0] < 9:
            return f"formant:{nums[0]}"
        return None
    aliases = {
        "language": "language", "name": "name", "gender": "gender",
        "pitch": "pitch", "voicing": "voicing", "consonants": "consonants",
        "roughness": "roughness", "flutter": "flutter", "clarity": "clarity",
        "formantshape": "clarity", "echo": "echo", "speed": "speed",
        "breath": "breath", "breathw": "breathw", "tone": "tone",
        "klatt": "klatt", "words": "words", "intonation": "intonation",
        "stresslength": "stressLength", "stressadd": "stressAdd",
        "stressamp": "stressAmp", "stressrule": "stressRule",
        "brackets": "brackets", "bracketsannounced": "bracketsAnnounced",
        "lowercasesentence": "lowercaseSentence", "spellingstress": "spellingStress",
        "phonemes": "phonemes", "dictionary": "dictionary", "dictrules": "dictrules",
        "stressopt": "stressOpt", "numbers": "numbers", "tunes": "tunes",
        "dict_min": "dictMin", "dictmin": "dictMin", "replace": "replace",
        "fast_test2": "fast", "mbrola": "mbrola", "maintainer": "maintainer",
        "status": "status", "variants": "variants",
    }
    if low in aliases:
        return aliases[low]
    if low in _DEFAULT_VALUES.get("internalOptions", {}):
        return low
    return None


def _generatedDirectiveLines(values, key):
    """Render only one directive family, filtering unrelated raw/extra lines."""
    try:
        candidate = _voiceBodyLines(values, present={key})
    except Exception:
        return []
    return [line for line in candidate if line and _directiveKeyFromLine(line) == key]


def _changedDirectiveKeys(values, baselineValues, currentPresent, baselinePresent):
    keys = set(currentPresent or ()) | set(baselinePresent or ())
    changed = set()
    for key in keys:
        if key in ("language", "name"):
            continue
        beforePresent = key in set(baselinePresent or ())
        afterPresent = key in set(currentPresent or ())
        if beforePresent != afterPresent:
            changed.add(key)
            continue
        if _generatedDirectiveLines(values, key) != _generatedDirectiveLines(baselineValues, key):
            changed.add(key)
    return changed


def _patchedVariantBodyLines(sourceText, values, baselineValues, currentPresent, baselinePresent):
    """Preserve an existing variant verbatim except for actually edited keys."""
    changed = _changedDirectiveKeys(values, baselineValues, currentPresent, baselinePresent)
    if changed:
        log.debug("eSpeak Voice Designer TEST48: runtime variant patches only %s", sorted(changed))
    sourceLines = str(sourceText or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    handled = set()
    for raw in sourceLines:
        stripped = str(raw or "").strip().casefold()
        if stripped.startswith((
            "// utf-8 espeak ng voice variant",
            "// created-with:",
            "// designed-language:",
            "// engine:",
        )):
            continue
        key = _directiveKeyFromLine(raw)
        if key in ("language", "name"):
            continue
        if key in changed:
            if key not in handled:
                out.extend(_generatedDirectiveLines(values, key))
                handled.add(key)
            continue
        out.append(raw)
    for key in sorted(changed):
        if key not in handled:
            out.extend(_generatedDirectiveLines(values, key))
    while out and not str(out[-1]).strip():
        out.pop()
    return out


def _variantTextFromSource(values, name, language, sourceText, baselineValues,
                           currentPresent, baselinePresent):
    """Save a derived variant without normalizing untouched source directives."""
    engine = "Klatt 6 SpeechPlayer" if int(values.get("klattSource", 0)) == 6 else "Standard eSpeak"
    lines = [
        "// UTF-8 eSpeak NG voice variant",
        "// created-with: eSpeak Voice Designer 0.2.46 TEST48",
        f"// designed-language: {language}",
        f"// engine: {engine}",
        "language variant",
        f"name {_safeFileName(name).replace(' ', '_')}",
    ]
    body = _patchedVariantBodyLines(
        sourceText, values, baselineValues, currentPresent, baselinePresent,
    )
    if body:
        lines.append("")
        lines.extend(body)
    lines.append("")
    return "\r\n".join(lines)


def _fullVoiceTextFromVariantSource(values, baseVoice, sourceText, baselineValues,
                                    currentPresent, baselinePresent,
                                    languageValues, languagePresent,
                                    runtimeName="esvdtest48"):
    """Build a full-path runtime voice while preserving real !v semantics.

    SetVoiceByFile needs a full voice file.  Language/parser options are emitted
    first, but timbral directives that a true !v load resets are NOT inherited
    from the language voice.  The original variant body is then patched only for
    keys the user actually changed.
    """
    baseVoice = _cleanSingleToken(baseVoice) or "en"
    priority = max(0, min(255, int(values.get("languagePriority", 5))))
    lines = [
        "// Runtime full voice generated by eSpeak Voice Designer TEST48",
        f"language {baseVoice} {priority}",
        f"name {runtimeName}",
    ]
    languageRuntimePresent = set(languagePresent or ()) - set(_VARIANT_RESET_DIRECTIVES)
    languageBody = _voiceBodyLines(languageValues, present=languageRuntimePresent)
    while languageBody and not str(languageBody[-1]).strip():
        languageBody.pop()
    if languageBody:
        lines.extend(languageBody)
    variantBody = _patchedVariantBodyLines(
        sourceText, values, baselineValues, currentPresent, baselinePresent,
    )
    if variantBody:
        if lines and str(lines[-1]).strip() and str(variantBody[0]).strip():
            lines.append("")
        lines.extend(variantBody)
    lines.append("")
    return "\r\n".join(lines)


def _effectiveVoiceState(baseVoice, variantPath=None):
    """Return the state that eSpeak really produces for this source.

    A `language variant` is loaded after VoiceReset(2): timbral voice quality
    starts from VoiceReset defaults, while language/prosody options remain from
    the selected language. This distinction is essential for transparent live
    editing of native !v variants.
    """
    languagePath = _languageFileForVoice(baseVoice)
    if languagePath:
        languageValues, languagePresent, _languageName = _readVariantFile(languagePath)
    else:
        languageValues, languagePresent = copy.deepcopy(_DEFAULT_VALUES), set()
    if variantPath and os.path.isfile(variantPath):
        variantValues, variantPresent, displayName = _readVariantFile(variantPath)
        values = _overlayValues(_variantResetBase(languageValues), variantValues, variantPresent)
    else:
        variantPresent = set()
        displayName = _("standard voice")
        values = copy.deepcopy(languageValues)
    return values, set(variantPresent), displayName, copy.deepcopy(languageValues), set(languagePresent)

def _variantDisplayName(path):
    try:
        _variantValues, _variantPresent, name = _readVariantFile(path)
        return name or os.path.basename(path)
    except Exception:
        return os.path.basename(path)


def _allVariantRecords(synth=None):
    """Return installed NVDA/eSpeak variants plus personal Designer variants.

    Native variants are never copied into the add-on data folder. Their list is
    taken from NVDA's active eSpeak synth (with a filesystem fallback), and the
    record points at the real file in espeak-ng-data/voices/!v.
    """
    records = []
    synth = synth or synthDriverHandler.getSynth()
    nativeDir = _nativeVariantDirectory()
    nativeItems = []
    try:
        available = getattr(synth, "availableVariants", None) if synth is not None else None
        if available:
            for variantId, info in available.items():
                variantId = str(variantId)
                display = str(getattr(info, "name", "") or variantId)
                nativeItems.append((variantId, display))
    except Exception:
        log.debugWarning("eSpeak Voice Designer: unable to enumerate NVDA availableVariants", exc_info=True)

    if not nativeItems:
        nativeItems.append(("none", _("No variant - standard voice")))
        if nativeDir:
            try:
                for fileName in sorted((n for n in os.listdir(nativeDir) if os.path.isfile(os.path.join(nativeDir, n))), key=str.casefold):
                    nativeItems.append((fileName, _variantDisplayName(os.path.join(nativeDir, fileName))))
            except Exception:
                log.debugWarning("eSpeak Voice Designer: unable to enumerate native eSpeak variants", exc_info=True)

    seen = set()
    # Keep NVDA's own order, with "none" first when it exists.
    nativeItems.sort(key=lambda item: (0 if item[0].casefold() == "none" else 1))
    for variantId, display in nativeItems:
        key = variantId.casefold()
        if key in seen:
            continue
        seen.add(key)
        if key == "none":
            records.append({
                "id": "none",
                "label": _("No variant - standard voice"),
                "path": None,
                "name": "none",
                "variantId": "none",
                "kind": "native",
            })
            continue
        path = _nativeVariantPath(variantId)
        label = display if display.casefold() == variantId.casefold() else f"{display} ({variantId})"
        records.append({
            "id": f"native:{variantId}",
            "label": label,
            "path": path,
            "name": variantId,
            "variantId": variantId,
            "kind": "native",
        })

    if not any(record.get("id") == "none" for record in records):
        records.insert(0, {
            "id": "none",
            "label": _("No variant - standard voice"),
            "path": None,
            "name": "none",
            "variantId": "none",
            "kind": "native",
        })

    root = _variantDirectory()
    try:
        langFolders = sorted((n for n in os.listdir(root) if n != "_espeak" and os.path.isdir(os.path.join(root, n))), key=str.casefold)
    except Exception:
        langFolders = []
    for lang in langFolders:
        folder = os.path.join(root, lang)
        try:
            names = sorted(
                (n for n in os.listdir(folder)
                 if os.path.isfile(os.path.join(folder, n)) and not n.casefold().endswith(_EDITOR_SIDECAR_SUFFIX)),
                key=str.casefold,
            )
        except Exception:
            continue
        for fileName in names:
            path = os.path.join(folder, fileName)
            display = _variantDisplayName(path)
            records.append({
                "id": f"user:{lang}:{fileName}",
                "label": _("Personal {language}: {name}").format(language=lang, name=display),
                "path": path,
                "name": fileName,
                "kind": "user",
                "language": lang,
            })
    return records



def _editorSidecarPath(variantPath):
    return str(variantPath) + _EDITOR_SIDECAR_SUFFIX


def _readEditorSidecar(variantPath):
    path = _editorSidecarPath(variantPath)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        if int(data.get("version", 0) or 0) > _EDITOR_SIDECAR_VERSION:
            return {}
        return data
    except FileNotFoundError:
        return {}
    except Exception:
        log.debugWarning("eSpeak Voice Designer: unable to read editor sidecar", exc_info=True)
        return {}


def _writeEditorSidecar(variantPath, data):
    payload = dict(data or {})
    payload["version"] = _EDITOR_SIDECAR_VERSION
    _writeTextAtomic(
        _editorSidecarPath(variantPath),
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _stockVariantRecords(records=None):
    records = records if records is not None else _allVariantRecords()
    return [record for record in records if record.get("kind") == "native"]


def _savedVariantRecords(records=None):
    records = records if records is not None else _allVariantRecords()
    return [record for record in records if record.get("kind") == "user"]


def _stockVariantChoices(records=None):
    """Real NVDA/eSpeak source variants only.

    There is deliberately no ``New variant`` entry. A native variant stays
    selected while its sound is still untouched so normal Up/Down, Home/End and
    PageUp/PageDown navigation works. As soon as the user edits a parameter the
    selector is cleared, because the current sound is no longer that exact
    installed NVDA/eSpeak variant.
    """
    records = records if records is not None else _allVariantRecords()
    return [(record["label"], record["id"]) for record in _stockVariantRecords(records)]


def _savedVariantChoices(records=None):
    """Choices for user-saved variants, labeled primarily by the real file name.

    The saved-variant selector is a file library.  Do not use the internal
    eSpeak ``name`` directive as its primary label: that can differ from the
    file name after older saves/renames and made the selector misleading.
    Add the language only when the same file name exists in more than one
    language folder.
    """
    saved = _savedVariantRecords(records)
    counts = {}
    for record in saved:
        key = str(record.get("name", "variant")).casefold()
        counts[key] = counts.get(key, 0) + 1

    choices = [(_NEW_VARIANT_LABEL, _NEW_VARIANT_ID)]
    for record in saved:
        fileName = str(record.get("name", "variant"))
        if counts.get(fileName.casefold(), 0) > 1:
            language = str(record.get("language", "") or "")
            label = f"{fileName} ({language})" if language else fileName
        else:
            label = fileName
        choices.append((label, record.get("id")))
    return choices


def _voiceBodyLines(values, present=None):
    lines = []
    has = (lambda key: present is None or key in present)

    gender = values.get("gender", "male")
    age = int(values.get("age", 0))
    if has("gender"):
        lines.append(f"gender {gender}" + (f" {age}" if age > 0 else ""))
    if has("maintainer") and values.get("maintainer"):
        lines.append("maintainer " + str(values["maintainer"]).strip())
    if has("status") and values.get("status"):
        lines.append("status " + str(values["status"]).strip())

    commentMetadata = (
        ("metaDescription", "description"),
        ("metaVersion", "voice-version"),
        ("metaLicense", "license"),
        ("metaContact", "contact"),
    )
    for field, label in commentMetadata:
        if has(field) and str(values.get(field, "")).strip():
            clean = " ".join(str(values[field]).replace("\r", " ").replace("\n", " ").split())
            lines.append(f"// {label}: {clean}")

    # Preserve the parser-level ``variants`` attribute when it was already
    # present in a source file, but do not expose or invent it for new variants.
    if has("variants") and values.get("variantsOverride"):
        lines.append(f"variants {int(values['variants'])}")

    phonemes = _cleanSingleToken(values.get("phonemes"))
    dictionary = _cleanSingleToken(values.get("dictionary"))
    if has("phonemes") and phonemes:
        lines.append(f"phonemes {phonemes}")
    if has("dictionary") and dictionary:
        lines.append(f"dictionary {dictionary}")

    formantLines = []
    for index, formant in enumerate(values["formants"]):
        if not has(f"formant:{index}"):
            continue
        freq, strength, width, freqAdd = [int(round(v)) for v in formant]
        formantLines.append(f"formant {index} {freq} {strength} {width} {freqAdd}")
    if formantLines:
        lines.append("")
        lines.extend(formantLines)

    qualityLines = []
    if has("pitch"):
        qualityLines.append(f"pitch {int(values['pitchBase'])} {int(values['pitchRange'])}")
    if has("voicing"):
        qualityLines.append(f"voicing {int(values['voicing'])}")
    if has("consonants"):
        qualityLines.append(f"consonants {int(values['consonantUnvoiced'])} {int(values['consonantVoiced'])}")
    if has("roughness"):
        qualityLines.append(f"roughness {int(values['roughness'])}")
    if has("flutter"):
        qualityLines.append(f"flutter {int(values['flutter'])}")
    if has("clarity"):
        qualityLines.append(f"clarity {int(values['clarity'])}")
    if has("echo"):
        qualityLines.append(f"echo {int(values['echoDelay'])} {int(values['echoAmp'])}")
    if has("speed"):
        qualityLines.append(f"speed {int(values['speed'])}")
    if has("breath"):
        qualityLines.append("breath " + " ".join(str(int(v)) for v in values["breath"]))
    if has("breathw"):
        qualityLines.append("breathw " + " ".join(str(int(v)) for v in values["breathw"]))
    if qualityLines:
        lines.append("")
        lines.extend(qualityLines)

    if has("tone"):
        toneCount = max(1, min(5, int(values.get("toneCount", 4))))
        toneParts = []
        for freq, amp in values["tone"][:toneCount]:
            toneParts.extend((str(int(freq)), str(int(amp))))
        lines += ["", "tone " + " ".join(toneParts)]

    klattSource = int(values.get("klattSource", 0))
    if has("klatt") and klattSource > 0:
        lines.append(f"klatt {klattSource}")

    if values.get("mbrolaOverride") and str(values.get("mbrolaVoice", "")).strip():
        mbrola = [str(values["mbrolaVoice"]).strip()]
        if str(values.get("mbrolaPhonemes", "")).strip():
            mbrola.append(str(values["mbrolaPhonemes"]).strip())
        mbrola.append(str(int(values.get("mbrolaSampleRate", 16000))))
        lines.append("mbrola " + " ".join(mbrola))

    if values.get("fastOverride"):
        lines.append(f"fast_test2 {int(values['fastValue'])}")

    if has("words"):
        lines.append(f"words {int(values['wordGap'])} {int(values['vowelPause'])}")
    if has("intonation") and int(values.get("intonation", 0)) > 0:
        lines.append(f"intonation {int(values['intonation'])}")

    # Ordering matters in eSpeak: stressLength must precede stressAdd.
    if has("stressLength"):
        lines.append("stressLength " + " ".join(str(int(v)) for v in values["stressLength"]))
    if has("stressAdd"):
        lines.append("stressAdd " + " ".join(str(int(v)) for v in values["stressAdd"]))
    if has("stressAmp"):
        lines.append("stressAmp " + " ".join(str(int(v)) for v in values["stressAmp"]))
    if has("stressRule"):
        lines.append("stressRule " + " ".join(str(int(v)) for v in values["stressRule"]))

    if has("brackets"):
        lines.append(f"brackets {int(values['brackets'])}")
    if has("bracketsAnnounced"):
        lines.append(f"bracketsAnnounced {int(values['bracketsAnnounced'])}")
    if has("lowercaseSentence") and values.get("lowercaseSentence"):
        lines.append("lowercaseSentence")
    if has("spellingStress") and values.get("spellingStress"):
        lines.append("spellingStress")

    dictrules = _parseIntList(values.get("dictrules"), 0, 31)
    if has("dictrules") and dictrules:
        lines.append("dictrules " + " ".join(str(v) for v in dictrules))
    stressOpt = _parseIntList(values.get("stressOpt"), 0, 31)
    if has("stressOpt") and stressOpt:
        lines.append("stressOpt " + " ".join(str(v) for v in stressOpt))
    numbers = _parseIntList(values.get("numbers"), 1, 63)
    if has("numbers") and numbers:
        lines.append("numbers " + " ".join(str(v) for v in numbers))
    if has("tunes") and str(values.get("tunes", "")).strip():
        lines.append("tunes " + str(values["tunes"]).strip())
    if has("dictMin"):
        lines.append(f"dict_min {int(values['dictMin'])}")

    for key, pair in values.get("internalOptions", {}).items():
        enabled, val = pair
        if enabled:
            lines.append(f"{key} {int(val)}")

    lines.extend(_normalizeRawLines(values.get("replacements", ""), "replace"))
    for extra in values.get("extraLines", []) or []:
        extra = str(extra).strip()
        if extra:
            lines.append(extra)
    lines.append("")
    return lines


def _variantText(values, name, language, present=None):
    engine = "Klatt 6 SpeechPlayer" if int(values.get("klattSource", 0)) == 6 else "Standard eSpeak"
    lines = [
        "// UTF-8 eSpeak NG voice variant",
        "// created-with: eSpeak Voice Designer 0.2.46 TEST48",
        f"// designed-language: {language}",
        f"// engine: {engine}",
        "language variant",
        f"name {_safeFileName(name).replace(' ', '_')}",
    ]
    lines.extend(_voiceBodyLines(values, present=present))
    return "\r\n".join(lines)


def _fullVoiceText(values, baseVoice, runtimeName="esvdtest48", present=None):
    baseVoice = _cleanSingleToken(baseVoice) or "en"
    priority = max(0, min(255, int(values.get("languagePriority", 5))))
    lines = [
        "// Runtime full voice generated by eSpeak Voice Designer TEST48",
        f"language {baseVoice} {priority}",
        f"name {runtimeName}",
    ]
    lines.extend(_voiceBodyLines(values, present=present))
    return "\r\n".join(lines)


def _writeTextAtomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tempPath = path + ".tmp"
    with open(tempPath, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tempPath, path)


def _forceStandardEspeakEngine(baseVoice, immediate=False):
    """Hard-reset eSpeak to the native non-Klatt voice before a source-0 runtime load.

    A full LoadVoice normally calls VoiceReset(0), which clears voice->klattv.
    We deliberately perform an additional espeak_SetVoiceByName here when the
    editor selects source 0.  This makes the transition from Klatt/SpeechPlayer
    explicit and prevents any previous Klatt generator state from surviving
    across live edits in NVDA's long-running eSpeak instance.
    """
    synth = synthDriverHandler.getSynth()
    if synth is None or getattr(synth, "name", "") != "espeak":
        raise RuntimeError(_("The current synthesizer is not eSpeak NG."))
    try:
        from synthDrivers import _espeak
    except Exception as e:
        raise RuntimeError(_("Unable to access the NVDA eSpeak driver: {error}").format(error=e))
    dll = getattr(_espeak, "espeakDLL", None)
    if dll is None or not hasattr(dll, "espeak_SetVoiceByName"):
        raise RuntimeError(_("This eSpeak build does not expose espeak_SetVoiceByName."))
    if immediate:
        try:
            synth.cancel()
        except Exception:
            log.debugWarning("eSpeak Voice Designer: unable to cancel speech before standard-engine reset", exc_info=True)
    name = (_cleanSingleToken(baseVoice) or "en").encode("utf-8")
    func = dll.espeak_SetVoiceByName
    try:
        func.argtypes = (ctypes.c_char_p,)
        func.restype = ctypes.c_int
    except Exception:
        pass
    result = int(func(name))
    if result != 0:
        raise RuntimeError(_("espeak_SetVoiceByName returned code {code}").format(code=result))


def _queueVoiceFileLoad(path, immediate=False):
    """Load the generated eSpeak voice.

    Normal/debounced edits may wait for current speech to finish.  Keyboard
    parameter changes must be audible *before* NVDA announces the new value,
    so immediate=True cancels any old utterance and loads synchronously.
    """
    synth = synthDriverHandler.getSynth()
    if synth is None or getattr(synth, "name", "") != "espeak":
        raise RuntimeError(_("The current synthesizer is not eSpeak NG."))

    try:
        from synthDrivers import _espeak
    except Exception as e:
        raise RuntimeError(_("Unable to access the NVDA eSpeak driver: {error}").format(error=e))

    dll = getattr(_espeak, "espeakDLL", None)
    if dll is None:
        raise RuntimeError(_("eSpeak NG is not initialized."))
    if not hasattr(dll, "espeak_SetVoiceByFile"):
        raise RuntimeError(_("This eSpeak build does not expose espeak_SetVoiceByFile."))

    encodedPath = os.fsencode(path)
    if len(encodedPath) >= 60:
        raise RuntimeError(_("The working voice path is too long for this eSpeak build."))

    def doLoad():
        func = dll.espeak_SetVoiceByFile
        try:
            func.argtypes = (ctypes.c_char_p,)
            func.restype = ctypes.c_int
        except Exception:
            pass
        result = int(func(encodedPath))
        if result != 0:
            raise RuntimeError(_("espeak_SetVoiceByFile returned code {code}").format(code=result))

    if immediate:
        # The old implementation always used _execWhenDone.  That made NVDA
        # announce the new numeric value with the *old* timbre and only then
        # loaded the edited voice.  Cancel old speech first and commit the
        # voice on the UI thread before wx/NVDA emits the value announcement.
        try:
            synth.cancel()
        except Exception:
            log.debugWarning("eSpeak Voice Designer: unable to cancel speech before live update", exc_info=True)
        doLoad()
        return

    execWhenDone = getattr(_espeak, "_execWhenDone", None)
    if callable(execWhenDone):
        execWhenDone(doLoad)
    else:
        doLoad()


def _queueVoiceVariantLoad(baseVoice, variantSuffix, immediate=False):
    """Load a working file through eSpeak's real voice+variant path.

    Unlike SetVoiceByFile, SetVoiceByName(base+suffix) calls LoadVoiceVariant:
    first the language voice is loaded with control=0, then the working file is
    applied with control=2 exactly like a native file in voices/!v.
    """
    synth = synthDriverHandler.getSynth()
    if synth is None or getattr(synth, "name", "") != "espeak":
        raise RuntimeError(_("The current synthesizer is not eSpeak NG."))
    try:
        from synthDrivers import _espeak
    except Exception as e:
        raise RuntimeError(_("Unable to access the NVDA eSpeak driver: {error}").format(error=e))
    dll = getattr(_espeak, "espeakDLL", None)
    if dll is None or not hasattr(dll, "espeak_SetVoiceByName"):
        raise RuntimeError(_("This eSpeak build does not expose espeak_SetVoiceByName."))
    baseVoice = _cleanSingleToken(baseVoice) or "en"
    suffix = str(variantSuffix or "")
    target = f"{baseVoice}+{suffix}"
    encodedTarget = target.encode("utf-8")
    if len(encodedTarget) >= 60:
        raise RuntimeError(_("The live eSpeak variant name is too long for this eSpeak build."))

    def doLoad():
        func = dll.espeak_SetVoiceByName
        try:
            func.argtypes = (ctypes.c_char_p,)
            func.restype = ctypes.c_int
        except Exception:
            pass
        result = int(func(encodedTarget))
        if result != 0:
            raise RuntimeError(_("espeak_SetVoiceByName returned code {code}").format(code=result))
        # Keep only the base voice mirrored into NVDA. The hidden runtime suffix
        # deliberately is not inserted into NVDA's public variant dictionary.
        try:
            synth._voice = baseVoice
        except Exception:
            pass

    if immediate:
        try:
            synth.cancel()
        except Exception:
            log.debugWarning("eSpeak Voice Designer: unable to cancel speech before live variant update", exc_info=True)
        doLoad()
        return
    execWhenDone = getattr(_espeak, "_execWhenDone", None)
    if callable(execWhenDone):
        execWhenDone(doLoad)
    else:
        doLoad()


def _restoreOriginalVoice(voice, variant):
    try:
        from synthDrivers import _espeak
        if hasattr(_espeak, "setVoiceAndVariant"):
            _espeak.setVoiceAndVariant(voice=voice, variant=variant or "none")
            return
    except Exception:
        log.debugWarning("eSpeak Voice Designer: private restore failed", exc_info=True)
    synth = synthDriverHandler.getSynth()
    if synth is not None and getattr(synth, "name", "") == "espeak":
        try:
            synth.voice = voice
            synth.variant = variant
        except Exception:
            log.error("eSpeak Voice Designer: unable to restore original eSpeak voice", exc_info=True)


def _formatValue(value):
    return str(int(round(float(value))))


def _numericValue(ctrl, fallback=0):
    try:
        text = str(ctrl.GetValue()).strip()
        if not text or text in ("-", "+"):
            return int(fallback)
        value = int(float(text.replace(",", ".")))
        return max(ctrl._esvdMinimum, min(ctrl._esvdMaximum, value))
    except Exception:
        return int(fallback)


def _expandNumericRangeForLoadedValue(ctrl, value):
    """Represent a real source integer exactly instead of normalizing it."""
    value = int(value)
    if value < ctrl._esvdMinimum:
        ctrl._esvdMinimum = value
    if value > ctrl._esvdMaximum:
        ctrl._esvdMaximum = value
    return value


def _numericCombo(parent, dialog, label, value, minimum, maximum, step=1, pageStep=10, onValueChanged=None):
    row = wx.BoxSizer(wx.HORIZONTAL)
    row.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    ctrl = wx.ComboBox(parent, choices=[], style=wx.CB_DROPDOWN)
    ctrl.SetName(label.rstrip(":"))
    ctrl._esvdMinimum = int(minimum)
    ctrl._esvdMaximum = int(maximum)
    ctrl._esvdStep = int(step)
    ctrl._esvdPageStep = int(pageStep)
    # UI ranges are editing guides. Real eSpeak files can legally contain
    # values outside several of them, so loading must never clamp the source.
    ctrl._esvdLast = _expandNumericRangeForLoadedValue(ctrl, value)
    ctrl.ChangeValue(_formatValue(ctrl._esvdLast))

    def setValue(newValue, apply=True):
        newValue = int(max(ctrl._esvdMinimum, min(ctrl._esvdMaximum, newValue)))
        ctrl._esvdLast = newValue
        ctrl.ChangeValue(_formatValue(newValue))
        if onValueChanged is not None:
            try:
                onValueChanged(ctrl, newValue)
            except Exception:
                log.debugWarning("eSpeak Voice Designer: numeric change callback failed", exc_info=True)
        if apply:
            dialog._applyBeforeAnnouncement()

    def _consume(evt):
        # Prevent wx from treating the same keystroke as navigation of a parent
        # choice/page after the numeric control has already handled it.
        try:
            evt.StopPropagation()
        except Exception:
            pass

    def onKey(evt):
        key = evt.GetKeyCode()
        if key == wx.WXK_UP:
            setValue(_numericValue(ctrl, ctrl._esvdLast) + ctrl._esvdStep)
            _consume(evt)
            return
        if key == wx.WXK_DOWN:
            setValue(_numericValue(ctrl, ctrl._esvdLast) - ctrl._esvdStep)
            _consume(evt)
            return
        if key == wx.WXK_PAGEUP:
            setValue(_numericValue(ctrl, ctrl._esvdLast) + ctrl._esvdPageStep)
            _consume(evt)
            return
        if key == wx.WXK_PAGEDOWN:
            setValue(_numericValue(ctrl, ctrl._esvdLast) - ctrl._esvdPageStep)
            _consume(evt)
            return
        if key == wx.WXK_SPACE and not evt.ControlDown() and not evt.AltDown():
            dialog._preview()
            _consume(evt)
            return
        evt.Skip()

    def onText(evt):
        try:
            valueNow = int(float(str(ctrl.GetValue()).strip().replace(",", ".")))
            if ctrl._esvdMinimum <= valueNow <= ctrl._esvdMaximum:
                ctrl._esvdLast = valueNow
                if onValueChanged is not None:
                    try:
                        onValueChanged(ctrl, valueNow)
                    except Exception:
                        log.debugWarning("eSpeak Voice Designer: numeric text callback failed", exc_info=True)
                dialog._scheduleApply()
        except Exception:
            pass
        evt.Skip()

    def onKillFocus(evt):
        valueNow = _numericValue(ctrl, ctrl._esvdLast)
        ctrl._esvdLast = valueNow
        ctrl.ChangeValue(_formatValue(valueNow))
        evt.Skip()

    ctrl.Bind(wx.EVT_CHAR_HOOK, onKey)
    ctrl.Bind(wx.EVT_TEXT, onText)
    ctrl.Bind(wx.EVT_KILL_FOCUS, onKillFocus)
    row.Add(ctrl, 1, wx.EXPAND)
    return row, ctrl


def _enableInitialLetterCycle(ctrl, useCharHook=False):
    """Cycle a textual Choice/ComboBox by the first alphanumeric character.

    Pressing a letter or digit selects the first item whose significant label
    begins with that character. Repeating the same key advances through all
    matching items and wraps to the first. Variant display prefixes are ignored
    so the cycle follows the actual variant file/name.
    """
    ctrl._esvdLastInitial = None

    def _onChar(evt):
        try:
            if evt.ControlDown() or evt.AltDown() or evt.MetaDown():
                ctrl._esvdLastInitial = None
                evt.Skip()
                return
        except Exception:
            pass

        try:
            code = evt.GetUnicodeKey()
        except Exception:
            code = 0
        if not code or code == getattr(wx, "WXK_NONE", 0):
            try:
                code = evt.GetKeyCode()
            except Exception:
                code = 0

        try:
            ch = chr(code)
        except Exception:
            ch = ""
        if len(ch) != 1 or not ch.isalnum():
            ctrl._esvdLastInitial = None
            evt.Skip()
            return

        initial = ch.casefold()
        matches = []
        for i in range(ctrl.GetCount()):
            try:
                text = str(ctrl.GetString(i)).strip()
            except Exception:
                text = ""
            # Variant selectors use descriptive prefixes in the visible label.
            # Search the actual variant name, e.g. "eSpeak: m1" by M and
            # "Personal it: Sandro" by S, rather than grouping everything
            # under E or P.
            folded = text.casefold()
            if folded.startswith("espeak:") or folded.startswith("personal ") or getattr(ctrl, "_esvdStripPrefix", False):
                if ":" in text:
                    text = text.split(":", 1)[1].strip()
            # Match the first meaningful alphanumeric character rather than
            # blindly text[0], so labels may contain punctuation/decorations.
            first = ""
            for candidate in text:
                if candidate.isalnum():
                    first = candidate.casefold()
                    break
            if first == initial:
                matches.append(i)

        if not matches:
            ctrl._esvdLastInitial = None
            evt.Skip()
            return

        current = ctrl.GetSelection()
        if ctrl._esvdLastInitial == initial and current in matches:
            pos = matches.index(current)
            target = matches[(pos + 1) % len(matches)]
        else:
            target = matches[0]

        ctrl.SetSelection(target)
        ctrl._esvdLastInitial = initial

        # SetSelection does not emit a selection event.  Emit the native event
        # for the actual control class so both wx.Choice and read-only
        # wx.ComboBox selectors apply their selection immediately.
        eventType = wx.EVT_COMBOBOX.typeId if isinstance(ctrl, wx.ComboBox) else wx.EVT_CHOICE.typeId
        choiceEvent = wx.CommandEvent(eventType, ctrl.GetId())
        choiceEvent.SetEventObject(ctrl)
        choiceEvent.SetInt(target)
        ctrl.GetEventHandler().ProcessEvent(choiceEvent)
        try:
            evt.StopPropagation()
        except Exception:
            pass

    # Most textual selectors work well with EVT_CHAR.  The global Section
    # ComboBox uses EVT_CHAR_HOOK so our repeated-initial cycling runs before
    # the native Windows type-ahead consumes the character.
    ctrl.Bind(wx.EVT_CHAR_HOOK if useCharHook else wx.EVT_CHAR, _onChar)


def _choiceRow(parent, dialog, label, choices, selectedValue):
    row = wx.BoxSizer(wx.HORIZONTAL)
    row.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    labels = [item[0] for item in choices]
    ctrl = wx.Choice(parent, choices=labels)
    ctrl.SetName(label.rstrip(":"))
    ctrl._esvdChoices = list(choices)
    index = 0
    for i, item in enumerate(choices):
        if item[1] == selectedValue:
            index = i
            break
    if labels:
        ctrl.SetSelection(index)
    ctrl.Bind(wx.EVT_CHOICE, lambda evt: dialog._applyBeforeAnnouncement())
    _enableInitialLetterCycle(ctrl)
    row.Add(ctrl, 1, wx.EXPAND)
    return row, ctrl


def _choiceValue(ctrl, fallback=None):
    try:
        index = ctrl.GetSelection()
        if 0 <= index < len(ctrl._esvdChoices):
            return ctrl._esvdChoices[index][1]
    except Exception:
        pass
    return fallback


def _checkRow(parent, dialog, label, value=False):
    ctrl = wx.CheckBox(parent, label=label)
    ctrl.SetValue(bool(value))
    ctrl.Bind(wx.EVT_CHECKBOX, lambda evt: dialog._applyBeforeAnnouncement())
    return ctrl


def _textRow(parent, dialog, label, value="", multiline=False, applyOnBlur=True):
    row = wx.BoxSizer(wx.VERTICAL if multiline else wx.HORIZONTAL)
    row.Add(wx.StaticText(parent, label=label), 0, (wx.BOTTOM if multiline else (wx.ALIGN_CENTER_VERTICAL | wx.RIGHT)), 6)
    style = wx.TE_MULTILINE if multiline else 0
    ctrl = wx.TextCtrl(parent, value=str(value or ""), style=style)
    ctrl.SetName(label.rstrip(":"))
    if applyOnBlur:
        ctrl.Bind(wx.EVT_KILL_FOCUS, lambda evt: (dialog._scheduleApply(), evt.Skip()))
    row.Add(ctrl, 1, wx.EXPAND)
    return row, ctrl


class VoiceDesignerDialog(wx.Dialog):
    def __init__(self, parent, previousSynthName=None, autoSwitchedSynth=False, workingState=None, initialFocusState=None):
        super().__init__(parent, title=f"{ADDON_TITLE} - {TEST_LABEL}", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        synth = synthDriverHandler.getSynth()
        if synth is None or getattr(synth, "name", "") != "espeak":
            raise RuntimeError(_("eSpeak NG must be the active NVDA synthesizer to use eSpeak Voice Designer."))

        self._synth = synth
        self._previousSynthName = previousSynthName
        self._autoSwitchedSynth = bool(autoSwitchedSynth and previousSynthName and previousSynthName != "espeak")
        self._originalVoice = str(getattr(synth, "voice", "") or "en")
        self._originalVariant = str(getattr(synth, "variant", "none") or "none")
        self._baseVoice = self._originalVoice
        self._baselineVoice = self._baseVoice
        self._variantRecords = _allVariantRecords(self._synth)

        # The initial editor state is the voice that is actually active in NVDA.
        # The native-variant selector is only a momentary source picker and is
        # therefore left with no selection. The current native variant is still
        # remembered internally as the Ctrl+Delete baseline.
        self._selectedVariantId = "none"
        wantedVariant = self._originalVariant.casefold()
        if wantedVariant != "none":
            for record in self._variantRecords:
                if record.get("kind") == "native" and str(record.get("variantId", record.get("name", ""))).casefold() == wantedVariant:
                    self._selectedVariantId = record["id"]
                    break
        initialRecord = next((r for r in self._variantRecords if r["id"] == self._selectedVariantId), self._variantRecords[0])
        self._selectedVariantFileName = str(initialRecord.get("name", "none"))
        self._sourceVariantPath = initialRecord.get("path")
        self._sourceVariantText = _readVoiceText(self._sourceVariantPath)
        self._sourceUsesVariantReset = bool(self._sourceVariantPath)
        (
            self._values,
            self._baselinePresent,
            self._selectedVariantDisplayName,
            self._languageValues,
            self._languagePresent,
        ) = _effectiveVoiceState(self._baseVoice, initialRecord.get("path"))
        self._baselineValues = copy.deepcopy(self._values)
        self._baselinePresent = set(self._baselinePresent)
        self._isNewVariant = True
        self._showSourceWhenClean = False
        self._nativeDirectActive = False

        # Without a draft, opening starts from the eSpeak voice/variant that is
        # actually active at entry. With a persistent draft, the draft replaces
        # the editor working state only inside the Designer and is applied after
        # the controls are built. Closing always restores the user's NVDA synth.

        # OK keeps the current unsaved work as a persistent editor draft.
        # The draft lives in the add-on configuration, survives NVDA/Windows
        # restarts, and is independent from the synthesizer NVDA uses outside
        # the Designer. Save Variant removes the draft after making it permanent.
        self._editorState = None
        self._exitFocusState = None
        if workingState:
            try:
                self._baseVoice = str(workingState.get("baseVoice", self._baseVoice))
                self._baselineVoice = str(workingState.get("baselineVoice", self._baseVoice))
                self._selectedVariantId = str(workingState.get("selectedVariantId", self._selectedVariantId))
                self._selectedVariantFileName = str(workingState.get("selectedVariantFileName", self._selectedVariantFileName))
                self._selectedVariantDisplayName = str(workingState.get("selectedVariantDisplayName", self._selectedVariantDisplayName))
                self._values = copy.deepcopy(workingState.get("values", self._values))
                self._baselineValues = copy.deepcopy(workingState.get("baselineValues", self._baselineValues))
                self._baselinePresent = set(workingState.get("baselinePresent", self._baselinePresent))
                self._isNewVariant = bool(workingState.get("isNewVariant", True))
                self._showSourceWhenClean = bool(workingState.get("showSourceWhenClean", False))
                self._sourceVariantPath = workingState.get("sourceVariantPath", self._sourceVariantPath)
                self._sourceVariantText = str(workingState.get("sourceVariantText", self._sourceVariantText) or "")
                self._sourceUsesVariantReset = bool(workingState.get("sourceUsesVariantReset", self._sourceUsesVariantReset))
                self._sourcePatchBaselineValues = copy.deepcopy(
                    workingState.get("sourcePatchBaselineValues", self._baselineValues)
                )
                # Re-read the native language source on every opening so the
                # runtime keeps the real language options from the installed
                # eSpeak build while preserving the unsaved editor values.
                languagePath = _languageFileForVoice(self._baseVoice)
                if languagePath:
                    self._languageValues, self._languagePresent, _languageDisplayName = _readVariantFile(languagePath)
                else:
                    self._languageValues, self._languagePresent = copy.deepcopy(_DEFAULT_VALUES), set()
            except Exception:
                log.debugWarning("eSpeak Voice Designer: unable to restore persistent editor draft", exc_info=True)

        # Every opening is an unsaved editing surface. The controls describe the
        # sound already in use; the native selector stays blank because it is only
        # used to choose a clean starting source. Keep the underlying Ctrl+Delete
        # baseline without advertising a native source as the current project.
        self._isNewVariant = True
        self._showSourceWhenClean = False

        # Keep a language-local source reference separate from the Ctrl+Delete
        # baseline.  Language switching must compare edits against the source
        # as it sounds in the *current* language, otherwise defaults from a
        # previously selected language can be mistaken for user overrides.
        try:
            (
                self._languageReferenceValues,
                self._languageReferencePresent,
                _refName,
                _refLanguageValues,
                _refLanguagePresent,
            ) = self._sourceStateForLanguage(self._baseVoice)
            self._languageReferenceValues = copy.deepcopy(self._languageReferenceValues)
            self._languageReferencePresent = set(self._languageReferencePresent)
        except Exception:
            self._languageReferenceValues = copy.deepcopy(self._values)
            self._languageReferencePresent = set(self._baselinePresent)

        self._initialWorkingState = workingState or {}
        self._initialFocusState = initialFocusState or {}
        self._committed = False
        self._applyTimer = None
        self._numericControls = []
        self._formantControls = []
        self._breathControls = []
        self._breathWControls = []
        self._toneControls = []
        self._stressLengthControls = []
        self._stressAddControls = []
        self._stressAmpControls = []
        self._internalOptionControls = {}
        # Multiple pages may expose the same real eSpeak voice parameter.
        # Linked numeric controls are kept synchronized before the live voice is reloaded.
        self._linkedNumericControls = {}
        # Canonical values for parameters exposed in more than one section.
        # This is the single source of truth for duplicated Formant/Klatt controls;
        # wx visual mirroring is no longer relied on for the audio state.
        self._linkedCanonicalValues = {}
        # Sparse eSpeak directives such as breath/breathw must never appear merely
        # because another control was edited.  Track whether the user actually
        # touched those families; source directives that already existed remain
        # preserved independently through referencePresent.
        self._sparseDirectiveTouched = set()
        self._linkSyncing = False
        self._pitchSyncing = False
        self._klattMirrorControls = {}
        # SpeechPlayer anti-ringing macro.  The anchor widths always represent
        # the currently loaded/saved baseline; the macro itself is intentionally
        # not an eSpeak directive.  Its result is saved as real formant widths.
        self._klattDampingApplying = False
        self._klattDampingAnchorWidths = [
            int(self._baselineValues["formants"][i][2]) for i in range(1, 5)
        ]
        # Editor-only consonant macros. Their audible result is always baked
        # into standard eSpeak directives (consonants/voicing/breath); only
        # these neutral macro positions and anchors live in the optional
        # .editor.json sidecar for personal variants.
        self._consonantMacroApplying = False
        self._consonantMacroState = {
            "strength": 100,
            "balance": 0,
            "body": 100,
            "anchors": {
                "unvoiced": int(self._baselineValues.get("consonantUnvoiced", 90)),
                "voiced": int(self._baselineValues.get("consonantVoiced", 100)),
                "voicing": int(self._baselineValues.get("voicing", 100)),
            },
        }
        # Editor-only Tone macros. Their result is baked into the ordinary
        # eSpeak `tone` frequency/amplitude pairs. The original anchor curve and
        # macro positions live only in the optional .editor.json sidecar.
        self._toneMacroApplying = False
        self._toneMacroState = {
            "brightness": 0,
            "body": 0,
            "presence": 0,
            "anchorCount": int(self._baselineValues.get("toneCount", 4)),
            "anchorTone": copy.deepcopy(self._baselineValues.get("tone", _DEFAULT_VALUES["tone"])),
        }
        self._sectionTitles = []
        self._pages = []

        outer = wx.BoxSizer(wx.VERTICAL)

        # TEST20: the four navigation selectors are global, always visible and
        # vertically stacked above the current section parameters.  They are
        # deliberately outside every page so changing section can never hide
        # Language, NVDA/eSpeak variants or saved variants.
        selectorBox = wx.BoxSizer(wx.VERTICAL)

        row, self.languageCombo = _choiceRow(
            self, self, _("Language / eSpeak voice:"), self._languageChoices(), self._baseVoice
        )
        selectorBox.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        self.languageCombo.Unbind(wx.EVT_CHOICE)
        self.languageCombo.Bind(wx.EVT_CHOICE, self._onLanguageChanged)

        variantChoices = _stockVariantChoices(self._variantRecords)
        row, self.variantCombo = _choiceRow(
            self, self, _("NVDA eSpeak variants:"), variantChoices, None
        )
        selectorBox.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        self.variantCombo._esvdStripPrefix = True
        # Native variants are starting points only. Do not show any of them as
        # the current project merely because the editor opened.
        self.variantCombo.SetSelection(wx.NOT_FOUND)
        self.variantCombo.Unbind(wx.EVT_CHOICE)
        self.variantCombo.Bind(wx.EVT_CHOICE, self._onVariantChanged)

        savedInitial = _NEW_VARIANT_ID if self._isNewVariant else (
            self._selectedVariantId if str(self._selectedVariantId).startswith("user:") else _NEW_VARIANT_ID
        )
        row, self.savedVariantCombo = _choiceRow(
            self, self, _("Saved variants:"), _savedVariantChoices(self._variantRecords), savedInitial
        )
        selectorBox.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        self.savedVariantCombo._esvdStripPrefix = True
        self.savedVariantCombo.Unbind(wx.EVT_CHOICE)
        self.savedVariantCombo.SetName(_("Saved variants, F2 renames, Delete removes the selected variant"))
        self.savedVariantCombo.Bind(wx.EVT_CHOICE, self._onSavedVariantChanged)

        sectionRow = wx.BoxSizer(wx.HORIZONTAL)
        sectionRow.Add(wx.StaticText(self, label=_("Section:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        # Use a real read-only ComboBox for sections.  Unlike wx.Choice, this
        # gives NVDA/Windows the same combo-box semantics as the other global
        # selectors and lets our alphanumeric type-ahead run reliably.
        self.sectionChoice = wx.ComboBox(self, style=wx.CB_READONLY)
        self.sectionChoice.SetName(_("Section"))
        self.sectionChoice.Bind(wx.EVT_COMBOBOX, self._onSectionChanged)
        sectionRow.Add(self.sectionChoice, 1, wx.EXPAND)
        selectorBox.Add(sectionRow, 0, wx.EXPAND)

        outer.Add(selectorBox, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 10)

        # Left/Right are intentionally reserved for the future step-size
        # controls.  Navigation in these four selectors is vertical only.
        for selector in (self.languageCombo, self.variantCombo, self.savedVariantCombo, self.sectionChoice):
            self._reserveHorizontalArrows(selector)

        # Plain page host: deliberately not a Notebook/BookCtrl.  Only one
        # ScrolledWindow is shown at a time, selected from the Choice above.
        # This removes native tab strips, overflow arrows and book focus stops.
        self.pageHost = wx.Panel(self)
        self.pageHostSizer = wx.BoxSizer(wx.VERTICAL)
        self.pageHost.SetSizer(self.pageHostSizer)
        outer.Add(self.pageHost, 1, wx.ALL | wx.EXPAND, 10)

        self._buildBasePage()
        self._buildConsonantsPage()
        self._buildFormantPages()
        self._buildBreathPage()
        self._buildTonePage()
        self._buildKlattPage()
        self._buildStressPages()
        self._buildInternalPage()
        self._buildMetadataPage()
        if self.sectionChoice.GetCount():
            self.sectionChoice.SetSelection(0)
            self._showSection(0)
        self._finalizeSectionPages()
        self._updatePitchDerivedControls(source="raw")
        self._syncAllLinkedNumeric()
        # Source-transparency firewall. If a widget ever represents a source
        # value differently, that representation becomes the comparison
        # baseline rather than being mistaken for a user edit.
        if not workingState or not hasattr(self, "_sourcePatchBaselineValues"):
            self._sourcePatchBaselineValues = copy.deepcopy(self._readControls())

        previewBox = wx.StaticBoxSizer(wx.StaticBox(self, label=_("Preview and save")), wx.VERTICAL)
        previewRow = wx.BoxSizer(wx.HORIZONTAL)
        previewRow.Add(wx.StaticText(self, label=_("Preview text:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.previewText = wx.TextCtrl(self, value=_DEFAULT_PREVIEW_TEXT)
        self.previewText.SetName(_("Preview text"))
        previewRow.Add(self.previewText, 1, wx.EXPAND)
        previewBox.Add(previewRow, 0, wx.EXPAND | wx.BOTTOM, 6)

        nameRow = wx.BoxSizer(wx.HORIZONTAL)
        nameRow.Add(wx.StaticText(self, label=_("Variant name:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        initialSaveName = "new-variant" if self._isNewVariant else (self._selectedVariantFileName if self._selectedVariantId != "none" else "new-variant")
        self.variantName = wx.TextCtrl(self, value=initialSaveName)
        self.variantName.SetName(_("Variant name"))
        # Draft metadata baselines let Preview text and Variant name be remembered
        # when they really change, without recreating a draft immediately after
        # Ctrl+S simply because the saved project uses custom text/name values.
        self._draftBaselinePreviewText = _DEFAULT_PREVIEW_TEXT
        self._draftBaselineVariantName = initialSaveName
        self.previewText.Bind(wx.EVT_TEXT, self._onDraftMetadataChanged)
        self.variantName.Bind(wx.EVT_TEXT, self._onDraftMetadataChanged)
        nameRow.Add(self.variantName, 1, wx.EXPAND)
        previewBox.Add(nameRow, 0, wx.EXPAND | wx.BOTTOM, 6)

        actionRow = wx.BoxSizer(wx.HORIZONTAL)
        self.previewButton = wx.Button(self, label=_("Preview"))
        self.previewButton.Bind(wx.EVT_BUTTON, lambda evt: self._preview())
        actionRow.Add(self.previewButton, 1, wx.RIGHT, 6)
        self.saveButton = wx.Button(self, label=_("Save variant"))
        self.saveButton.Bind(wx.EVT_BUTTON, self._onSave)
        actionRow.Add(self.saveButton, 1, wx.RIGHT, 6)
        self.installButton = wx.Button(self, label=_("Install in NVDA"))
        self.installButton.SetName(_("Install variant in NVDA, Ctrl+Shift+S"))
        self.installButton.Bind(wx.EVT_BUTTON, self._onInstallInNvda)
        actionRow.Add(self.installButton, 1, wx.RIGHT, 6)
        self.resetButton = wx.Button(self, label=_("Restore base (Ctrl+Delete)"))
        self.resetButton.Bind(wx.EVT_BUTTON, self._onRestoreVariant)
        actionRow.Add(self.resetButton, 1, wx.RIGHT, 6)
        self.helpButton = wx.Button(self, label=_("Help"))
        self.helpButton.SetName(_("Open help, Alt+H"))
        self.helpButton.Bind(wx.EVT_BUTTON, self._onHelp)
        actionRow.Add(self.helpButton, 1)
        previewBox.Add(actionRow, 0, wx.EXPAND)
        outer.Add(previewBox, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            outer.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.SetSizer(outer)
        self.SetMinSize((720, 650))
        self.SetSize((820, 790))
        self.CentreOnScreen()

        self.Bind(wx.EVT_BUTTON, self._onOk, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self._onCancel, id=wx.ID_CANCEL)
        self.Bind(wx.EVT_CLOSE, self._onClose)
        self._bindAccelerators()
        self.Bind(wx.EVT_CHAR_HOOK, self._onDialogCharHook)

        # Populate every page from the actually selected/current eSpeak variant.
        self._loadValuesIntoControls(self._values)
        if self._initialWorkingState:
            try:
                self._setChoice(self.languageCombo, self._baseVoice)
                self._refreshVariantChoices(self._selectedVariantId)
                self.variantName.ChangeValue(str(self._initialWorkingState.get("variantName", self.variantName.GetValue())))
                self.previewText.ChangeValue(str(self._initialWorkingState.get("previewText", self.previewText.GetValue())))
                self._draftBaselineVariantName = str(
                    self._initialWorkingState.get("draftBaselineVariantName", self._draftBaselineVariantName)
                )
                self._draftBaselinePreviewText = str(
                    self._initialWorkingState.get("draftBaselinePreviewText", self._draftBaselinePreviewText)
                )
                self._restoreConsonantMacroState(self._initialWorkingState.get("consonantMacroState"), self._values)
                self._restoreToneMacroState(self._initialWorkingState.get("toneMacroState"), self._values)
                kdState = self._initialWorkingState.get("klattDampingState")
                if isinstance(kdState, dict):
                    anchors = kdState.get("anchorWidths")
                    if isinstance(anchors, list) and len(anchors) >= 4:
                        self._klattDampingAnchorWidths = [max(0, min(800, int(x))) for x in anchors[:4]]
                    self._setCtrl(self.klattDamping, max(0, min(100, int(kdState.get("value", 0) or 0))))
                sectionIndex = int(self._initialWorkingState.get("sectionIndex", 0))
                if 0 <= sectionIndex < len(self._pages):
                    self.sectionChoice.SetSelection(sectionIndex)
                    self._showSection(sectionIndex)
            except Exception:
                log.debugWarning("eSpeak Voice Designer: unable to restore persistent draft UI state", exc_info=True)
        # A persistent draft must sound like the draft as soon as the Designer
        # reopens. A clean opening without a draft remains read-only and keeps
        # the currently selected eSpeak voice untouched until the first edit.
        if self._initialWorkingState:
            try:
                self._applyNow(markDirty=False, immediate=True)
            except Exception:
                log.debugWarning("eSpeak Voice Designer: unable to activate persistent draft", exc_info=True)
        self._refreshModifiedTitle()
        if self._initialFocusState:
            wx.CallAfter(self._restoreFocusState, copy.deepcopy(self._initialFocusState))
        else:
            wx.CallAfter(self.languageCombo.SetFocus)

    def _newPage(self, title):
        panel = wx.ScrolledWindow(self.pageHost, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        panel.SetScrollRate(0, 20)
        sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(sizer)
        self.pageHostSizer.Add(panel, 1, wx.EXPAND)
        if self._pages:
            panel.Hide()
        self._pages.append(panel)
        self._sectionTitles.append(title)
        self.sectionChoice.Append(title)

        def onChildFocus(evt, page=panel):
            try:
                child = evt.GetWindow()
                if child is not None:
                    page.ScrollChildIntoView(child)
            except Exception:
                pass
            evt.Skip()

        panel.Bind(wx.EVT_CHILD_FOCUS, onChildFocus)
        return panel, sizer

    def _finalizeSectionPages(self):
        for page in self._pages:
            try:
                page.GetSizer().Layout()
                page.FitInside()
            except Exception:
                pass
        self.pageHostSizer.Layout()

    def _showSection(self, index):
        if not (0 <= index < len(self._pages)):
            return
        for i, page in enumerate(self._pages):
            page.Show(i == index)
        self.pageHostSizer.Layout()
        try:
            self._pages[index].Layout()
            self._pages[index].FitInside()
        except Exception:
            pass

    def _reserveHorizontalArrows(self, ctrl):
        """Keep Left/Right free on the four global navigation selectors.

        The native-variant Choice can intentionally have no visible selection
        when the editor opens on an arbitrary current eSpeak state.  Windows
        wx.Choice does not start Up/Down navigation from wx.NOT_FOUND, although
        Home/End/PageUp/PageDown do seed an index.  Bootstrap Up/Down from the
        internally remembered source so arrow-only navigation always works.
        """
        def onKey(evt):
            key = evt.GetKeyCode()
            noModifiers = not evt.ControlDown() and not evt.AltDown() and not evt.ShiftDown()
            if ctrl is self.variantCombo and key in (wx.WXK_UP, wx.WXK_DOWN) and noModifiers:
                try:
                    current = ctrl.GetSelection()
                except Exception:
                    current = wx.NOT_FOUND
                if current == wx.NOT_FOUND and ctrl.GetCount() > 0:
                    anchorId = str(getattr(self, "_selectedVariantId", "none") or "none")
                    anchorIndex = -1
                    for i, item in enumerate(getattr(ctrl, "_esvdChoices", ())):
                        try:
                            if str(item[1]) == anchorId:
                                anchorIndex = i
                                break
                        except Exception:
                            continue
                    if anchorIndex < 0:
                        target = 0 if key == wx.WXK_DOWN else ctrl.GetCount() - 1
                    else:
                        delta = 1 if key == wx.WXK_DOWN else -1
                        target = (anchorIndex + delta) % ctrl.GetCount()
                    ctrl.SetSelection(target)
                    choiceEvent = wx.CommandEvent(wx.EVT_CHOICE.typeId, ctrl.GetId())
                    choiceEvent.SetEventObject(ctrl)
                    choiceEvent.SetInt(target)
                    ctrl.GetEventHandler().ProcessEvent(choiceEvent)
                    try:
                        evt.StopPropagation()
                    except Exception:
                        pass
                    return
            if key in (wx.WXK_LEFT, wx.WXK_RIGHT) and not evt.ControlDown() and not evt.AltDown():
                try:
                    evt.StopPropagation()
                except Exception:
                    pass
                return
            evt.Skip()
        ctrl.Bind(wx.EVT_CHAR_HOOK, onKey)

    def _cycleVariantSelectorFocus(self):
        """Alt+V toggles focus between NVDA/eSpeak and personal variant libraries."""
        try:
            focused = self._normalizeFocusWindow(wx.Window.FindFocus())
        except Exception:
            focused = None
        target = self.savedVariantCombo if focused is self.variantCombo else self.variantCombo
        try:
            target.SetFocus()
        except Exception:
            pass

    def _onSectionChanged(self, evt):
        index = self.sectionChoice.GetSelection()
        self._showSection(index)
        evt.Skip()

    def _focusFirstInCurrentSection(self):
        index = self.sectionChoice.GetSelection()
        if not (0 <= index < len(self._pages)):
            return
        page = self._pages[index]

        def walk(window):
            for child in window.GetChildren():
                if isinstance(child, (wx.StaticText, wx.StaticLine, wx.StaticBox)):
                    continue
                try:
                    if child.IsShown() and child.IsEnabled() and child.AcceptsFocus():
                        child.SetFocus()
                        return True
                except Exception:
                    pass
                if walk(child):
                    return True
            return False

        walk(page)

    def _cycleSection(self, delta):
        count = len(self._pages)
        if not count:
            return
        current = self.sectionChoice.GetSelection()
        if current < 0:
            current = 0
        target = (current + delta) % count
        self.sectionChoice.SetSelection(target)
        self._showSection(target)
        wx.CallAfter(self._focusFirstInCurrentSection)
        try:
            ui.message(self._sectionTitles[target])
        except Exception:
            pass

    def _interactiveControls(self):
        """Return editor controls in a stable creation/tree order."""
        targetTypes = (wx.ComboBox, wx.Choice, wx.TextCtrl, wx.CheckBox, wx.Button)
        controls = []

        def walk(window):
            for child in window.GetChildren():
                if isinstance(child, targetTypes):
                    controls.append(child)
                walk(child)

        walk(self)
        return controls

    def _normalizeFocusWindow(self, window):
        """Map a native/internal focused child back to its wx editor control."""
        targetTypes = (wx.ComboBox, wx.Choice, wx.TextCtrl, wx.CheckBox, wx.Button)
        current = window
        while current is not None and current is not self:
            if isinstance(current, targetTypes):
                return current
            try:
                current = current.GetParent()
            except Exception:
                break
        return None

    def _sectionIndexForWindow(self, window):
        current = window
        while current is not None and current is not self:
            for index, page in enumerate(self._pages):
                if current is page:
                    return index
            try:
                current = current.GetParent()
            except Exception:
                break
        index = self.sectionChoice.GetSelection()
        return index if 0 <= index < len(self._pages) else 0

    def _controlSignature(self, ctrl):
        try:
            className = ctrl.__class__.__name__
        except Exception:
            className = ""
        try:
            name = str(ctrl.GetName() or "")
        except Exception:
            name = ""
        try:
            label = str(ctrl.GetLabel() or "")
        except Exception:
            label = ""
        return className, name, label

    def _captureFocusState(self):
        try:
            focused = self._normalizeFocusWindow(wx.Window.FindFocus())
        except Exception:
            focused = None
        sectionIndex = self.sectionChoice.GetSelection()
        if sectionIndex < 0:
            sectionIndex = 0
        state = {"sectionIndex": int(sectionIndex)}
        if focused is None:
            return state

        sectionIndex = self._sectionIndexForWindow(focused)
        state["sectionIndex"] = int(sectionIndex)
        controls = self._interactiveControls()
        try:
            globalIndex = controls.index(focused)
        except ValueError:
            globalIndex = -1
        className, name, label = self._controlSignature(focused)
        same = [c for c in controls if self._controlSignature(c) == (className, name, label)]
        try:
            occurrence = same.index(focused)
        except ValueError:
            occurrence = 0
        state.update({
            "className": className,
            "name": name,
            "label": label,
            "occurrence": int(occurrence),
            "globalIndex": int(globalIndex),
        })
        return state

    def _restoreFocusState(self, state):
        if not state:
            self.languageCombo.SetFocus()
            return
        try:
            sectionIndex = int(state.get("sectionIndex", 0))
        except Exception:
            sectionIndex = 0
        if not (0 <= sectionIndex < len(self._pages)):
            sectionIndex = 0
        self.sectionChoice.SetSelection(sectionIndex)
        self._showSection(sectionIndex)

        controls = self._interactiveControls()
        className = str(state.get("className", ""))
        name = str(state.get("name", ""))
        label = str(state.get("label", ""))
        candidates = [c for c in controls if self._controlSignature(c) == (className, name, label)]
        target = None
        try:
            occurrence = int(state.get("occurrence", 0))
        except Exception:
            occurrence = 0
        if candidates and 0 <= occurrence < len(candidates):
            target = candidates[occurrence]
        if target is None:
            try:
                globalIndex = int(state.get("globalIndex", -1))
            except Exception:
                globalIndex = -1
            if 0 <= globalIndex < len(controls):
                target = controls[globalIndex]
        if target is None:
            self._focusFirstInCurrentSection()
            return

        # If the remembered control belongs to a page, ensure that exact page
        # is visible before setting focus. Controls below the page host (preview,
        # save name, buttons) keep the remembered current section unchanged.
        targetSection = self._sectionIndexForWindow(target)
        current = target
        belongsToPage = False
        while current is not None and current is not self:
            if current in self._pages:
                belongsToPage = True
                break
            try:
                current = current.GetParent()
            except Exception:
                break
        if belongsToPage and 0 <= targetSection < len(self._pages):
            self.sectionChoice.SetSelection(targetSection)
            self._showSection(targetSection)
        try:
            target.SetFocus()
            if belongsToPage:
                self._pages[targetSection].ScrollChildIntoView(target)
        except Exception:
            self._focusFirstInCurrentSection()

    def _cycleSectionByInitial(self, ch):
        """Cycle Section by an alphanumeric initial at dialog level.

        wx.ComboBox on Windows owns an internal native edit/list window which can
        consume type-ahead before a handler bound to the ComboBox sees it.  The
        dialog-level EVT_CHAR_HOOK runs before that native handling, so Section
        gets deterministic NVDA-friendly first-character navigation.
        """
        if not ch or len(ch) != 1 or not ch.isalnum():
            return False
        initial = ch.casefold()
        matches = []
        for i, title in enumerate(self._sectionTitles):
            first = ""
            for candidate in str(title).strip():
                if candidate.isalnum():
                    first = candidate.casefold()
                    break
            if first == initial:
                matches.append(i)
        if not matches:
            return False
        current = self.sectionChoice.GetSelection()
        lastInitial = getattr(self.sectionChoice, "_esvdLastInitial", None)
        if lastInitial == initial and current in matches:
            pos = matches.index(current)
            target = matches[(pos + 1) % len(matches)]
        else:
            target = matches[0]
        self.sectionChoice._esvdLastInitial = initial
        self.sectionChoice.SetSelection(target)
        self._showSection(target)
        try:
            ui.message(self._sectionTitles[target])
        except Exception:
            pass
        return True

    def _onDialogCharHook(self, evt):
        key = evt.GetKeyCode()
        # Section type-ahead is handled here rather than on wx.ComboBox itself.
        # This catches the character before the native Windows combo consumes it.
        try:
            focused = self._normalizeFocusWindow(wx.Window.FindFocus())
        except Exception:
            focused = None
        if focused is self.sectionChoice and not evt.ControlDown() and not evt.AltDown() and not evt.MetaDown():
            try:
                code = evt.GetUnicodeKey()
            except Exception:
                code = 0
            if not code or code == getattr(wx, "WXK_NONE", 0):
                code = key
            try:
                ch = chr(code)
            except Exception:
                ch = ""
            if self._cycleSectionByInitial(ch):
                try:
                    evt.StopPropagation()
                except Exception:
                    pass
                return
            self.sectionChoice._esvdLastInitial = None
        if key == wx.WXK_F2 and not evt.ControlDown() and not evt.AltDown() and not evt.ShiftDown():
            focused = self._normalizeFocusWindow(wx.Window.FindFocus())
            if focused is self.savedVariantCombo:
                self._renameSelectedSavedVariant()
                try:
                    evt.StopPropagation()
                except Exception:
                    pass
                return
        if key == wx.WXK_DELETE and evt.ControlDown() and not evt.AltDown():
            self._onRestoreVariant(None)
            try:
                evt.StopPropagation()
            except Exception:
                pass
            return
        if key == wx.WXK_DELETE and not evt.ControlDown() and not evt.AltDown() and not evt.ShiftDown():
            # Plain Delete is destructive only in the personal-variant library.
            # Everywhere else it keeps the normal control/text-edit behaviour.
            if focused is self.savedVariantCombo:
                self._deleteSelectedSavedVariant()
                try:
                    evt.StopPropagation()
                except Exception:
                    pass
                return
        if evt.ControlDown() and key == wx.WXK_TAB:
            self._cycleSection(-1 if evt.ShiftDown() else 1)
            try:
                evt.StopPropagation()
            except Exception:
                pass
            return
        evt.Skip()

    def _languageChoices(self):
        items = []
        seen = set()
        try:
            available = getattr(self._synth, "availableVoices", {})
            for identifier, info in available.items():
                ident = str(identifier)
                if not ident or ident in seen:
                    continue
                seen.add(ident)
                display = str(getattr(info, "displayName", "") or ident)
                lang = str(getattr(info, "language", "") or "")
                suffix = f" - {lang}" if lang and lang.lower() != ident.lower() else ""
                items.append((f"{display} ({ident}){suffix}", ident))
        except Exception:
            log.debugWarning("eSpeak Voice Designer: unable to enumerate eSpeak voices", exc_info=True)
        if self._originalVoice not in seen:
            items.append((self._originalVoice, self._originalVoice))
        items.sort(key=lambda item: item[0].casefold())
        return items

    def _linkedCallback(self, key):
        return lambda ctrl, value: self._syncLinkedNumeric(key, ctrl, value)

    def _markSparseDirectiveTouched(self, directive):
        try:
            self._sparseDirectiveTouched.add(str(directive))
        except Exception:
            pass

    def _breathLinkedCallback(self, key):
        def callback(ctrl, value):
            self._syncLinkedNumeric(key, ctrl, value)
            self._markSparseDirectiveTouched("breath")
        return callback

    def _sparseTouchCallback(self, directive):
        return lambda ctrl, value: self._markSparseDirectiveTouched(directive)

    def _klattWidthCallback(self, formantIndex, key):
        def callback(ctrl, value):
            self._syncLinkedNumeric(key, ctrl, value)
            # A manual F1-F4 bandwidth edit takes precedence over the macro.
            # Keep the baseline anchor intact so the user can always return to
            # the source widths with the dedicated button.
            if not self._klattDampingApplying and hasattr(self, "klattDamping"):
                self.klattDamping._esvdLast = 0
                self.klattDamping.ChangeValue("0")
        return callback

    def _captureKlattDampingAnchors(self, values=None):
        source = values if values is not None else self._baselineValues
        try:
            self._klattDampingAnchorWidths = [
                int(source["formants"][i][2]) for i in range(1, 5)
            ]
        except Exception:
            self._klattDampingAnchorWidths = [100, 100, 100, 100]
        if hasattr(self, "klattDamping"):
            self.klattDamping._esvdLast = 0
            self.klattDamping.ChangeValue("0")

    def _setKlattWidthsFromDamping(self, amount):
        amount = max(0, min(100, int(amount)))
        # 0% = original source bandwidths.  100% = four times the source
        # bandwidth.  A larger bandwidth means lower Q and therefore much less
        # bell-like ringing.  SpeechPlayer applies these multipliers directly
        # to F1-F4 for every frame.
        factor = 1.0 + (3.0 * amount / 100.0)
        self._klattDampingApplying = True
        try:
            for offset, formantIndex in enumerate(range(1, 5)):
                anchor = self._klattDampingAnchorWidths[offset]
                value = int(round(anchor * factor))
                primary = self._formantControls[formantIndex][2]
                value = max(primary._esvdMinimum, min(primary._esvdMaximum, value))
                primary._esvdLast = value
                primary.ChangeValue(_formatValue(value))
                self._syncLinkedNumeric(f"formant:{formantIndex}:2", primary, value)
        finally:
            self._klattDampingApplying = False

    def _onKlattDampingChanged(self, ctrl, value):
        self._setKlattWidthsFromDamping(value)

    def _onKlattClean(self, evt):
        # SpeechPlayer is the Klatt path where the variant widths are applied
        # consistently to F1-F4 on every frame.  70% is deliberately strong
        # enough to kill the obvious metallic/bell ringing while leaving room
        # for further manual tuning.
        self._setChoice(self.klattSourceCombo, 6)
        self._values["klattSource"] = 6
        self.klattDamping._esvdLast = 70
        self.klattDamping.ChangeValue("70")
        self._setKlattWidthsFromDamping(70)
        self._applyBeforeAnnouncement()
        ui.message(_("Klatt 6 SpeechPlayer clean, formant resonances damped"))
        if evt is not None:
            evt.Skip()

    def _onKlattOriginalWidths(self, evt):
        self.klattDamping._esvdLast = 0
        self.klattDamping.ChangeValue("0")
        self._setKlattWidthsFromDamping(0)
        self._applyBeforeAnnouncement()
        ui.message(_("Base variant widths and resonances restored"))
        if evt is not None:
            evt.Skip()

    def _onKlattStandard(self, evt):
        self._setChoice(self.klattSourceCombo, 0)
        self._values["klattSource"] = 0
        self._applyBeforeAnnouncement()
        ui.message(_("Standard eSpeak formant synthesis, Klatt disabled"))
        if evt is not None:
            evt.Skip()

    def _registerLinkedNumeric(self, key, ctrl):
        self._linkedNumericControls.setdefault(key, []).append(ctrl)
        return ctrl

    def _syncLinkedNumeric(self, key, sourceCtrl, value):
        # Store the real parameter value first.  Formant and Klatt pages are
        # merely two views of the same eSpeak parameter and must never be able
        # to diverge even if wx delays a visual control update.
        value = int(value)
        self._linkedCanonicalValues[key] = value
        if self._linkSyncing:
            return
        self._linkSyncing = True
        try:
            for ctrl in self._linkedNumericControls.get(key, []):
                if ctrl is sourceCtrl:
                    continue
                value2 = _expandNumericRangeForLoadedValue(ctrl, value)
                ctrl._esvdLast = value2
                ctrl.ChangeValue(_formatValue(value2))
        finally:
            self._linkSyncing = False

    def _syncAllLinkedNumeric(self):
        """Copy primary values to mirrors and refresh their canonical state."""
        if not self._linkedNumericControls:
            return
        self._linkSyncing = True
        try:
            for key, controls in self._linkedNumericControls.items():
                if not controls:
                    continue
                value = _numericValue(controls[0], controls[0]._esvdLast)
                self._linkedCanonicalValues[key] = int(value)
                for ctrl in controls[1:]:
                    value2 = _expandNumericRangeForLoadedValue(ctrl, value)
                    ctrl._esvdLast = value2
                    ctrl.ChangeValue(_formatValue(value2))
        finally:
            self._linkSyncing = False

    def _applyCanonicalLinkedValues(self, values):
        """Bake all duplicated UI controls into one canonical eSpeak state."""
        for key, rawValue in self._linkedCanonicalValues.items():
            value = int(rawValue)
            if key.startswith("formant:"):
                try:
                    _prefix, formantIndex, fieldIndex = key.split(":")
                    values["formants"][int(formantIndex)][int(fieldIndex)] = value
                except Exception:
                    pass
            elif key.startswith("breath:"):
                try:
                    values["breath"][int(key.split(":", 1)[1])] = value
                except Exception:
                    pass
            elif key in ("voicing", "flutter", "consonantUnvoiced", "consonantVoiced"):
                values[key] = value
        return values

    def _pitchInfoValues(self):
        p1 = _numericValue(self.pitchBase, 82) if hasattr(self, "pitchBase") else 82
        p2 = _numericValue(self.pitchRange, 118) if hasattr(self, "pitchRange") else 118
        span = p2 - p1
        internalBase = p1 - 9
        factor = (1.0 + ((p1 - 82.0) / 82.0) / 4.0) * 100.0
        return p1, p2, span, internalBase, factor

    def _updatePitchDerivedControls(self, source=None):
        if self._pitchSyncing or not hasattr(self, "pitchBase"):
            return
        self._pitchSyncing = True
        try:
            p1 = _numericValue(self.pitchBase, 82)
            p2 = _numericValue(self.pitchRange, 118)
            if source == "span" and hasattr(self, "pitchSpan"):
                span = _numericValue(self.pitchSpan, p2 - p1)
                p2 = max(self.pitchRange._esvdMinimum, min(self.pitchRange._esvdMaximum, p1 + span))
                self.pitchRange._esvdLast = p2
                self.pitchRange.ChangeValue(_formatValue(p2))
                # If P2 had to be clamped, reflect the actual serialized span.
                actualSpan = p2 - p1
                self.pitchSpan._esvdLast = actualSpan
                self.pitchSpan.ChangeValue(_formatValue(actualSpan))
            else:
                span = p2 - p1
                if hasattr(self, "pitchSpan"):
                    span2 = _expandNumericRangeForLoadedValue(self.pitchSpan, span)
                    self.pitchSpan._esvdLast = span2
                    self.pitchSpan.ChangeValue(_formatValue(span2))
            internalBase = p1 - 9
            factor = (1.0 + ((p1 - 82.0) / 82.0) / 4.0) * 100.0
            if hasattr(self, "pitchInternalBase"):
                self.pitchInternalBase.ChangeValue(str(internalBase))
            if hasattr(self, "pitchFormantFactor"):
                self.pitchFormantFactor.ChangeValue(f"{factor:.1f}")
        finally:
            self._pitchSyncing = False

    def _onPitchRawChanged(self, ctrl, value):
        self._updatePitchDerivedControls(source="raw")

    def _onPitchSpanChanged(self, ctrl, value):
        self._updatePitchDerivedControls(source="span")

    def _readOnlyRow(self, parent, label, value=""):
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        ctrl = wx.TextCtrl(parent, value=str(value), style=wx.TE_READONLY)
        ctrl.SetName(label.rstrip(":"))
        row.Add(ctrl, 1, wx.EXPAND)
        return row, ctrl

    def _buildBasePage(self):
        panel, s = self._newPage(_("Voice"))
        # Language and both variant libraries are global selectors in TEST20.
        # The Voice section now begins directly with its first editable voice
        # parameter, which is also the Alt+L destination for this section.
        genderChoices = [(_("Male"), "male"), (_("Female"), "female"), (_("Unknown"), "unknown")]
        row, self.genderCombo = _choiceRow(panel, self, _("Gender, metadata only:"), genderChoices, self._values["gender"])
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)

        row, self.pitchBase = _numericCombo(
            panel, self, _("Variant pitch P1, base Hz:"), 78, 20, 300, 1, 10, onValueChanged=self._onPitchRawChanged
        )
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.pitchRange = _numericCombo(
            panel, self, _("Variant pitch P2, second range value:"), 115, 20, 300, 1, 10, onValueChanged=self._onPitchRawChanged
        )
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.pitchSpan = _numericCombo(
            panel, self, _("Pitch span P2 minus P1:"), 37, -280, 280, 1, 10, onValueChanged=self._onPitchSpanChanged
        )
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.pitchInternalBase = self._readOnlyRow(panel, _("Internal eSpeak base P1 minus 9 Hz:"), "69")
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.pitchFormantFactor = self._readOnlyRow(panel, _("Nominal formant adaptation factor from P1 percent:"), "98.8")
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 7)
        row, self.voicing = _numericCombo(
            panel, self, _("Voicing:"), 165, 0, 255, 1, 10, onValueChanged=self._consonantDirectCallback("voicing", "voicing")
        )
        self._registerLinkedNumeric("voicing", self.voicing)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.consonantUnvoiced = _numericCombo(
            panel, self, _("Unvoiced consonants:"), 194, 0, 255, 1, 10,
            onValueChanged=self._consonantDirectCallback("unvoiced", "consonantUnvoiced"),
        )
        self._registerLinkedNumeric("consonantUnvoiced", self.consonantUnvoiced)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.consonantVoiced = _numericCombo(
            panel, self, _("Voiced consonants:"), 255, 0, 255, 1, 10,
            onValueChanged=self._consonantDirectCallback("voiced", "consonantVoiced"),
        )
        self._registerLinkedNumeric("consonantVoiced", self.consonantVoiced)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.roughness = _numericCombo(panel, self, _("Roughness:"), 3, 0, 7, 1, 1)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.flutter = _numericCombo(
            panel, self, _("Flutter, pitch micro-variation:"), 2, 0, 100, 1, 10, onValueChanged=self._linkedCallback("flutter")
        )
        self._registerLinkedNumeric("flutter", self.flutter)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.clarity = _choiceRow(
            panel, self, _("Clarity / formant harmonic construction:"), _CLARITY_CHOICES, self._values.get("clarity", 4)
        )
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        clarityInfo = wx.StaticText(
            panel,
            label=_(
                "Clarity 0-4 progressively extends harmonic construction from F1 to F5. "
                "Value 5 keeps F1-F5 but uses squarer peaks. It mainly affects standard formant "
                "synthesis; Klatt 6 / SpeechPlayer may not follow it."
            ),
        )
        clarityInfo.Wrap(680)
        s.Add(clarityInfo, 0, wx.EXPAND | wx.BOTTOM, 7)
        row, self.speed = _numericCombo(panel, self, _("Speed %:"), 100, 1, 500, 1, 10)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.echoDelay = _numericCombo(panel, self, _("Echo delay ms:"), 0, 0, 250, 1, 10)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.echoAmp = _numericCombo(panel, self, _("Echo amplitude %:"), 0, 0, 100, 1, 10)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        self._numericControls.extend([
            self.pitchBase, self.pitchRange, self.pitchSpan, self.voicing,
            self.consonantUnvoiced, self.consonantVoiced, self.roughness,
            self.flutter, self.speed, self.echoDelay, self.echoAmp,
        ])

    def _consonantMacroAnchorsFromValues(self, values=None):
        source = values if values is not None else self._values
        return {
            "unvoiced": int(source.get("consonantUnvoiced", 90)),
            "voiced": int(source.get("consonantVoiced", 100)),
            "voicing": int(source.get("voicing", 100)),
        }

    def _resetConsonantMacros(self, values=None):
        self._consonantMacroState = {
            "strength": 100,
            "balance": 0,
            "body": 100,
            "anchors": self._consonantMacroAnchorsFromValues(values),
        }
        if hasattr(self, "consonantStrengthMacro"):
            self._setCtrl(self.consonantStrengthMacro, 100)
            self._setCtrl(self.consonantBalanceMacro, 0)
            self._setCtrl(self.consonantBodyMacro, 100)

    def _restoreConsonantMacroState(self, data, values=None):
        values = values if values is not None else self._values
        anchorsDefault = self._consonantMacroAnchorsFromValues(values)
        data = data if isinstance(data, dict) else {}
        anchors = data.get("anchors") if isinstance(data.get("anchors"), dict) else {}
        state = {
            "strength": max(0, min(200, int(data.get("strength", 100) or 100))),
            "balance": max(-100, min(100, int(data.get("balance", 0) or 0))),
            "body": max(0, min(200, int(data.get("body", 100) or 100))),
            "anchors": {
                "unvoiced": max(0, min(255, int(anchors.get("unvoiced", anchorsDefault["unvoiced"]) or 0))),
                "voiced": max(0, min(255, int(anchors.get("voiced", anchorsDefault["voiced"]) or 0))),
                "voicing": max(0, min(255, int(anchors.get("voicing", anchorsDefault["voicing"]) or 0))),
            },
        }
        self._consonantMacroState = state
        if hasattr(self, "consonantStrengthMacro"):
            self._setCtrl(self.consonantStrengthMacro, state["strength"])
            self._setCtrl(self.consonantBalanceMacro, state["balance"])
            self._setCtrl(self.consonantBodyMacro, state["body"])

    def _consonantDirectCallback(self, part, linkedKey):
        def callback(ctrl, value):
            self._syncLinkedNumeric(linkedKey, ctrl, value)
            if self._consonantMacroApplying or not hasattr(self, "consonantStrengthMacro"):
                return
            # A direct edit becomes a new neutral macro anchor. This prevents a
            # stale macro position from unexpectedly re-writing a hand-tuned
            # standard eSpeak value on the next adjustment.
            if part in ("unvoiced", "voiced"):
                self._consonantMacroState["strength"] = 100
                self._consonantMacroState["balance"] = 0
                self._setCtrl(self.consonantStrengthMacro, 100)
                self._setCtrl(self.consonantBalanceMacro, 0)
                self._consonantMacroState.setdefault("anchors", {})["unvoiced"] = _numericValue(self.consonantUnvoiced, 90)
                self._consonantMacroState.setdefault("anchors", {})["voiced"] = _numericValue(self.consonantVoiced, 100)
            elif part == "voicing":
                self._consonantMacroState["body"] = 100
                self._setCtrl(self.consonantBodyMacro, 100)
                self._consonantMacroState.setdefault("anchors", {})["voicing"] = int(value)
        return callback

    def _applyConsonantMacros(self):
        if not hasattr(self, "consonantStrengthMacro"):
            return
        strength = _numericValue(self.consonantStrengthMacro, 100)
        balance = _numericValue(self.consonantBalanceMacro, 0)
        body = _numericValue(self.consonantBodyMacro, 100)
        state = self._consonantMacroState
        anchors = state.setdefault("anchors", self._consonantMacroAnchorsFromValues())
        state["strength"] = strength
        state["balance"] = balance
        state["body"] = body

        # Strength scales both consonant noise components. Balance then tilts
        # their ratio without introducing any proprietary voice-file command:
        # +100 favours voiced noise, -100 favours unvoiced noise.
        baseU = float(anchors.get("unvoiced", 90)) * strength / 100.0
        baseV = float(anchors.get("voiced", 100)) * strength / 100.0
        if balance >= 0:
            unvoiced = baseU * (1.0 - 0.75 * balance / 100.0)
            voiced = baseV * (1.0 + 0.75 * balance / 100.0)
        else:
            b = (-balance) / 100.0
            unvoiced = baseU * (1.0 + 0.75 * b)
            voiced = baseV * (1.0 - 0.75 * b)
        voicing = float(anchors.get("voicing", 100)) * body / 100.0

        self._consonantMacroApplying = True
        try:
            for key, primary, raw in (
                ("consonantUnvoiced", self.consonantUnvoiced, unvoiced),
                ("consonantVoiced", self.consonantVoiced, voiced),
                ("voicing", self.voicing, voicing),
            ):
                value = int(round(max(0, min(255, raw))))
                primary._esvdLast = value
                primary.ChangeValue(_formatValue(value))
                self._syncLinkedNumeric(key, primary, value)
        finally:
            self._consonantMacroApplying = False

    def _onConsonantMacroChanged(self, ctrl, value):
        self._applyConsonantMacros()

    def _buildConsonantsPage(self):
        panel, s = self._newPage(_("Consonants"))
        info = wx.StaticText(
            panel,
            label=_(
                "The first three controls are Voice Designer macros. They are not written to the variant file: "
                "their result is converted into the standard eSpeak consonants and voicing parameters. "
                "The real controls below can still be edited directly."
            ),
        )
        info.Wrap(680)
        s.Add(info, 0, wx.EXPAND | wx.BOTTOM, 8)

        row, self.consonantStrengthMacro = _numericCombo(
            panel, self, _("Macro consonant strength %:"), 100, 0, 200, 1, 10,
            onValueChanged=self._onConsonantMacroChanged,
        )
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.consonantBalanceMacro = _numericCombo(
            panel, self, _("Macro voiced / unvoiced balance, negative unvoiced, positive voiced:"), 0, -100, 100, 1, 10,
            onValueChanged=self._onConsonantMacroChanged,
        )
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.consonantBodyMacro = _numericCombo(
            panel, self, _("Macro voiced consonant and sonorant body %:"), 100, 0, 200, 1, 10,
            onValueChanged=self._onConsonantMacroChanged,
        )
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 8)
        self._numericControls.extend([self.consonantStrengthMacro, self.consonantBalanceMacro, self.consonantBodyMacro])

        s.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.BOTTOM, 7)
        row, c = _numericCombo(
            panel, self, _("Real eSpeak - unvoiced consonants:"), self._values["consonantUnvoiced"], 0, 255, 1, 10,
            onValueChanged=self._consonantDirectCallback("unvoiced", "consonantUnvoiced"),
        )
        self._registerLinkedNumeric("consonantUnvoiced", c)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5); self._numericControls.append(c)
        row, c = _numericCombo(
            panel, self, _("Real eSpeak - voiced consonants:"), self._values["consonantVoiced"], 0, 255, 1, 10,
            onValueChanged=self._consonantDirectCallback("voiced", "consonantVoiced"),
        )
        self._registerLinkedNumeric("consonantVoiced", c)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5); self._numericControls.append(c)
        row, c = _numericCombo(
            panel, self, _("Real eSpeak - Voicing / voiced body:"), self._values["voicing"], 0, 255, 1, 10,
            onValueChanged=self._consonantDirectCallback("voicing", "voicing"),
        )
        self._registerLinkedNumeric("voicing", c)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5); self._numericControls.append(c)
        row, c = _numericCombo(
            panel, self, _("Real eSpeak - Breath 1:"), self._values["breath"][0], 0, 255, 1, 10,
            onValueChanged=self._breathLinkedCallback("breath:0"),
        )
        self._registerLinkedNumeric("breath:0", c)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5); self._numericControls.append(c)

    def _buildFormantPages(self):
        for first, last in ((0, 2), (3, 5), (6, 8)):
            panel, s = self._newPage(_("Formants {first}-{last}").format(first=first, last=last))
            if first == 0:
                info = wx.StaticText(
                    panel,
                    label=_(
                        "With Klatt 6 / SpeechPlayer, Frequency, Offset and Width for F1-F6 are the same parameters "
                        "shown in the Klatt section. Formant Strength belongs to the standard formant synthesizer "
                        "and SpeechPlayer does not use it directly."
                    ),
                )
                info.Wrap(680)
                s.Add(info, 0, wx.EXPAND | wx.BOTTOM, 8)
            for i in range(first, last + 1):
                original = self._values["formants"][i]
                controls = []
                key = f"formant:{i}:0"
                row, c = _numericCombo(
                    panel, self, _("Formant {index} Frequency %:").format(index=i), original[0], 0, 300, 1, 10, onValueChanged=self._linkedCallback(key)
                )
                self._registerLinkedNumeric(key, c)
                s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4); controls.append(c)
                row, c = _numericCombo(panel, self, _("Formant {index} Strength %:").format(index=i), original[1], 0, 255, 1, 10)
                s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4); controls.append(c)
                key = f"formant:{i}:2"
                row, c = _numericCombo(
                    panel, self, _("Formant {index} Width / damping %:").format(index=i), original[2], 0, 800, 1, 10, onValueChanged=(self._klattWidthCallback(i, key) if 1 <= i <= 4 else self._linkedCallback(key))
                )
                self._registerLinkedNumeric(key, c)
                s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4); controls.append(c)
                key = f"formant:{i}:3"
                row, c = _numericCombo(
                    panel, self, _("Formant {index} Offset Hz:").format(index=i), original[3], -5000, 5000, 1, 100, onValueChanged=self._linkedCallback(key)
                )
                self._registerLinkedNumeric(key, c)
                s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 8); controls.append(c)
                self._formantControls.append(controls)
                self._numericControls.extend(controls)

    def _buildBreathPage(self):
        panel, s = self._newPage(_("Breath"))
        for i in range(8):
            key = f"breath:{i}" if i in (0, 1) else None
            row, c = _numericCombo(
                panel, self, _("Breath formant {index}:").format(index=i + 1), self._values["breath"][i], 0, 255, 1, 10,
                onValueChanged=(self._breathLinkedCallback(key) if key else self._sparseTouchCallback("breath")),
            )
            if key:
                self._registerLinkedNumeric(key, c)
            s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4)
            self._breathControls.append(c)
            self._numericControls.append(c)
        s.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 5)
        for i in range(8):
            row, c = _numericCombo(
                panel, self, _("Breath width {index}:").format(index=i + 1), self._values["breathw"][i], 0, 2000, 1, 50,
                onValueChanged=self._sparseTouchCallback("breathw"),
            )
            s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4)
            self._breathWControls.append(c)
            self._numericControls.append(c)

    def _toneAnchorsFromValues(self, values=None):
        source = values if values is not None else self._values
        count = max(1, min(5, int(source.get("toneCount", 4))))
        tone = copy.deepcopy(source.get("tone", _DEFAULT_VALUES["tone"]))
        while len(tone) < 5:
            tone.append(copy.deepcopy(tone[-1] if tone else [3000, 128]))
        return count, [[int(pair[0]), int(pair[1])] for pair in tone[:5]]

    def _setToneMacroControls(self, brightness=0, body=0, presence=0):
        for attr, value in (("toneBrightnessMacro", brightness), ("toneBodyMacro", body), ("tonePresenceMacro", presence)):
            ctrl = getattr(self, attr, None)
            if ctrl is not None:
                self._setCtrl(ctrl, max(-100, min(100, int(value))))

    def _resetToneMacros(self, values=None):
        count, tone = self._toneAnchorsFromValues(values)
        self._toneMacroState = {
            "brightness": 0,
            "body": 0,
            "presence": 0,
            "anchorCount": count,
            "anchorTone": tone,
        }
        self._setToneMacroControls(0, 0, 0)

    def _captureToneMacroAnchorsFromControls(self):
        if not self._toneControls:
            return
        count = int(_choiceValue(self.toneCountCombo, 4)) if hasattr(self, "toneCountCombo") else 4
        tone = []
        for i, pair in enumerate(self._toneControls):
            fallback = self._values.get("tone", _DEFAULT_VALUES["tone"])[i]
            tone.append([_numericValue(pair[0], fallback[0]), _numericValue(pair[1], fallback[1])])
        self._toneMacroState = {
            "brightness": 0,
            "body": 0,
            "presence": 0,
            "anchorCount": max(1, min(5, count)),
            "anchorTone": tone,
        }
        self._setToneMacroControls(0, 0, 0)

    def _restoreToneMacroState(self, state, values=None):
        if not isinstance(state, dict):
            self._resetToneMacros(values)
            return
        count, fallbackTone = self._toneAnchorsFromValues(values)
        anchors = state.get("anchorTone")
        parsed = []
        if isinstance(anchors, list):
            for pair in anchors[:5]:
                try:
                    parsed.append([max(0, min(8000, int(pair[0]))), max(0, min(255, int(pair[1])))])
                except Exception:
                    parsed = []
                    break
        if not parsed:
            parsed = fallbackTone
        while len(parsed) < 5:
            parsed.append(copy.deepcopy(parsed[-1] if parsed else [3000, 128]))
        brightness = max(-100, min(100, int(state.get("brightness", 0) or 0)))
        body = max(-100, min(100, int(state.get("body", 0) or 0)))
        presence = max(-100, min(100, int(state.get("presence", 0) or 0)))
        self._toneMacroState = {
            "brightness": brightness,
            "body": body,
            "presence": presence,
            "anchorCount": max(1, min(5, int(state.get("anchorCount", count) or count))),
            "anchorTone": parsed[:5],
        }
        self._setToneMacroControls(brightness, body, presence)

    def _toneMacroWeights(self, frequency):
        f = max(0.0, min(8000.0, float(frequency)))
        # Brightness is a spectral tilt around ~1.5 kHz: positive values raise
        # the upper points and gently reduce the lowest ones.
        brightness = max(-1.0, min(1.0, (f - 1500.0) / 2500.0))
        # Body is concentrated below ~1.8 kHz, strongest in the low-mid region.
        body = max(0.0, 1.0 - abs(f - 500.0) / 1400.0)
        # Presence is a broad bell centred near 2.3 kHz.
        presence = max(0.0, 1.0 - abs(f - 2300.0) / 1900.0)
        return brightness, body, presence

    def _applyToneMacrosToControls(self):
        state = self._toneMacroState
        brightness = int(state.get("brightness", 0))
        body = int(state.get("body", 0))
        presence = int(state.get("presence", 0))
        anchors = copy.deepcopy(state.get("anchorTone") or _DEFAULT_VALUES["tone"])
        self._toneMacroApplying = True
        try:
            for i, pair in enumerate(self._toneControls):
                try:
                    freq, amp = anchors[i]
                except Exception:
                    freq, amp = _DEFAULT_VALUES["tone"][min(i, len(_DEFAULT_VALUES["tone"]) - 1)]
                wb, wbody, wp = self._toneMacroWeights(freq)
                delta = (brightness * wb * 0.55) + (body * wbody * 0.55) + (presence * wp * 0.55)
                newAmp = max(0, min(255, int(round(float(amp) + delta))))
                self._setCtrl(pair[0], int(freq))
                self._setCtrl(pair[1], newAmp)
        finally:
            self._toneMacroApplying = False

    def _onToneMacroChanged(self, ctrl, value):
        if self._toneMacroApplying:
            return
        self._toneMacroState["brightness"] = _numericValue(self.toneBrightnessMacro, 0)
        self._toneMacroState["body"] = _numericValue(self.toneBodyMacro, 0)
        self._toneMacroState["presence"] = _numericValue(self.tonePresenceMacro, 0)
        self._applyToneMacrosToControls()

    def _toneDirectCallback(self, index, field):
        def callback(ctrl, value):
            if self._toneMacroApplying:
                return
            # A manual edit becomes the new neutral Tone curve. This avoids a
            # stale macro position re-writing a point the user just tuned.
            self._captureToneMacroAnchorsFromControls()
        return callback

    def _onToneCountChanged(self, evt):
        self._captureToneMacroAnchorsFromControls()
        self._applyBeforeAnnouncement()
        evt.Skip()

    def _buildTonePage(self):
        panel, s = self._newPage(_("Tone"))
        info = wx.StaticText(
            panel,
            label=_(
                "Tone is the harmonic amplitude curve for the voiced part of the voice. 128 is neutral; "
                "points are interpolated up to 8 kHz. The macros below are Designer-only controls: "
                "only standard eSpeak tone points are saved in the variant file."
            ),
        )
        info.Wrap(680)
        s.Add(info, 0, wx.EXPAND | wx.BOTTOM, 8)

        row, self.toneBrightnessMacro = _numericCombo(
            panel, self, _("Tone macro Darker minus / Brighter plus:"), 0, -100, 100, 1, 10, onValueChanged=self._onToneMacroChanged
        )
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.toneBodyMacro = _numericCombo(
            panel, self, _("Tone macro Body, less / more:"), 0, -100, 100, 1, 10, onValueChanged=self._onToneMacroChanged
        )
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        row, self.tonePresenceMacro = _numericCombo(
            panel, self, _("Tone macro Presence, less / more:"), 0, -100, 100, 1, 10, onValueChanged=self._onToneMacroChanged
        )
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 8)
        self._numericControls.extend([self.toneBrightnessMacro, self.toneBodyMacro, self.tonePresenceMacro])

        countChoices = [(_("{count} points").format(count=i), i) for i in range(1, 6)]
        row, self.toneCountCombo = _choiceRow(panel, self, _("Number of Tone points:"), countChoices, self._values["toneCount"])
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 8)
        self.toneCountCombo.Unbind(wx.EVT_CHOICE)
        self.toneCountCombo.Bind(wx.EVT_CHOICE, self._onToneCountChanged)
        for i in range(5):
            freq, amp = self._values["tone"][i]
            row, f = _numericCombo(
                panel, self, _("Tone {index} Frequency Hz:").format(index=i + 1), freq, 0, 8000, 1, 100,
                onValueChanged=self._toneDirectCallback(i, "frequency"),
            )
            s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4)
            row, a = _numericCombo(
                panel, self, _("Tone {index} Amplitude, 128 neutral:").format(index=i + 1), amp, 0, 255, 1, 10,
                onValueChanged=self._toneDirectCallback(i, "amplitude"),
            )
            s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 7)
            self._toneControls.append([f, a])
            self._numericControls.extend([f, a])
        self._resetToneMacros(self._values)

    def _buildKlattPage(self):
        panel, s = self._newPage(_("Klatt"))
        row, self.klattSourceCombo = _choiceRow(panel, self, _("Klatt engine / source:"), _KLATT_CHOICES, self._values["klattSource"])
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 8)
        # Source changes are engine changes and must be heard before NVDA announces the choice.
        self.klattSourceCombo.Unbind(wx.EVT_CHOICE)
        self.klattSourceCombo.Bind(wx.EVT_CHOICE, self._onKlattChanged)

        info = wx.StaticText(
            panel,
            label=_(
                "Standard eSpeak uses normal formant synthesis. Klatt 6 SpeechPlayer uses Voicing, "
                "Breath 1 / aspiration (the first value written in the breath directive), F1-F6 and F1-F4 bandwidths. "
                "Increasing width increases bandwidth, lowers Q and damps metallic or bell-like resonances. "
                "F5 and F6 already use a very wide fixed bandwidth."
            ),
        )
        info.Wrap(680)
        s.Add(info, 0, wx.EXPAND | wx.BOTTOM, 8)

        row, self.klattDamping = _numericCombo(
            panel, self, _("Klatt 6 global resonance damping %:"), 0, 0, 100, 1, 10,
            onValueChanged=self._onKlattDampingChanged,
        )
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)
        self._numericControls.append(self.klattDamping)

        row, c = _numericCombo(
            panel, self, _("Klatt Voicing:"), self._values["voicing"], 0, 255, 1, 10,
            onValueChanged=self._consonantDirectCallback("voicing", "voicing"),
        )
        self._registerLinkedNumeric("voicing", c); self._klattMirrorControls["voicing"] = c
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4); self._numericControls.append(c)

        row, c = _numericCombo(
            panel, self, _("Klatt pitch Flutter:"), self._values["flutter"], 0, 100, 1, 10,
            onValueChanged=self._linkedCallback("flutter"),
        )
        self._registerLinkedNumeric("flutter", c); self._klattMirrorControls["flutter"] = c
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4); self._numericControls.append(c)

        row, c = _numericCombo(
            panel, self, _("Klatt 6 SpeechPlayer Aspiration / Breath 1:"), self._values["breath"][0], 0, 255, 1, 10,
            onValueChanged=self._linkedCallback("breath:0"),
        )
        self._registerLinkedNumeric("breath:0", c); self._klattMirrorControls["breath:0"] = c
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 8); self._numericControls.append(c)

        for i in range(1, 7):
            s.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 4)
            key = f"formant:{i}:0"
            row, c = _numericCombo(
                panel, self, _("Klatt F{index} Frequency %:").format(index=i), self._values["formants"][i][0], 0, 300, 1, 10,
                onValueChanged=self._linkedCallback(key),
            )
            self._registerLinkedNumeric(key, c); self._klattMirrorControls[key] = c
            s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4); self._numericControls.append(c)

            key = f"formant:{i}:3"
            row, c = _numericCombo(
                panel, self, _("Klatt F{index} Offset Hz:").format(index=i), self._values["formants"][i][3], -5000, 5000, 1, 100,
                onValueChanged=self._linkedCallback(key),
            )
            self._registerLinkedNumeric(key, c); self._klattMirrorControls[key] = c
            s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4); self._numericControls.append(c)

            if i <= 4:
                key = f"formant:{i}:2"
                suffix = _(" (higher = less resonance; SpeechPlayer: F1-F4)")
                row, c = _numericCombo(
                    panel, self, _("Klatt F{index} Width / damping %{suffix}:").format(index=i, suffix=suffix), self._values["formants"][i][2], 0, 800, 1, 10,
                    onValueChanged=self._klattWidthCallback(i, key),
                )
                self._registerLinkedNumeric(key, c); self._klattMirrorControls[key] = c
                s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5); self._numericControls.append(c)

    def _onKlattChanged(self, evt):
        self._values["klattSource"] = int(_choiceValue(self.klattSourceCombo, 0))
        self._applyBeforeAnnouncement()
        evt.Skip()

    def _buildStressPages(self):
        panel, s = self._newPage(_("Stress Length"))
        info = wx.StaticText(panel, label=_("Relative vowel length for the 8 stress levels. Changing a value automatically makes the voice a New variant."))
        info.Wrap(680)
        s.Add(info, 0, wx.EXPAND | wx.BOTTOM, 8)
        for i, name in _STRESS_VISIBLE:
            row, c = _numericCombo(panel, self, f"{name}:", self._values["stressLength"][i], -255, 500, 1, 10)
            s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4)
            self._stressLengthControls.append(c); self._numericControls.append(c)

        panel, s = self._newPage(_("Stress Add"))
        info = wx.StaticText(panel, label=_("Correction added to Stress Length. eSpeak applies Stress Length before Stress Add; the Designer preserves this order automatically."))
        info.Wrap(680)
        s.Add(info, 0, wx.EXPAND | wx.BOTTOM, 8)
        for i, name in _STRESS_VISIBLE:
            row, c = _numericCombo(panel, self, f"{name}:", self._values["stressAdd"][i], -255, 255, 1, 10)
            s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4)
            self._stressAddControls.append(c); self._numericControls.append(c)

        panel, s = self._newPage(_("Stress Amp"))
        info = wx.StaticText(panel, label=_("Relative vowel amplitude for the 8 stress levels."))
        info.Wrap(680)
        s.Add(info, 0, wx.EXPAND | wx.BOTTOM, 8)
        for i, name in _STRESS_VISIBLE:
            row, c = _numericCombo(panel, self, f"{name}:", self._values["stressAmp"][i], 0, 255, 1, 10)
            s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4)
            self._stressAmpControls.append(c); self._numericControls.append(c)

    def _buildMetadataPage(self):
        panel, s = self._newPage(_("Metadata"))
        info = wx.StaticText(
            panel,
            label=_(
                "Variant metadata. Age, Maintainer and Status use compatible eSpeak attributes; "
                "Description, Version, License and Website/contact are saved as // comments and do not change the sound."
            ),
        )
        info.Wrap(680)
        s.Add(info, 0, wx.EXPAND | wx.BOTTOM, 8)

        row, self.age = _numericCombo(panel, self, _("Voice age, metadata:"), 0, 0, 150, 1, 10)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)
        row, self.maintainerText = _textRow(panel, self, _("Maintainer / Author:"))
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)
        row, self.statusCombo = _choiceRow(panel, self, _("Status:"), _STATUS_CHOICES, "")
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)
        row, self.metaDescriptionText = _textRow(panel, self, _("Description:"))
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)
        row, self.metaVersionText = _textRow(panel, self, _("Voice version:"))
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)
        row, self.metaLicenseText = _textRow(panel, self, _("License:"))
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)
        row, self.metaContactText = _textRow(panel, self, _("Website / contact:"))
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)
        self._numericControls.append(self.age)

    def _buildInternalPage(self):
        panel, s = self._newPage(_("Internals and backends"))
        info = wx.StaticText(panel, label=_("These options are accepted by the eSpeak parser but are poorly or not documented. They remain inactive until you select the corresponding Enable check box."))
        info.Wrap(680)
        s.Add(info, 0, wx.EXPAND | wx.BOTTOM, 8)
        for key, label in (
            ("apostrophe", "Apostrophe"),
            ("l_dieresis", "l_dieresis"),
            ("l_prefix", "l_prefix"),
            ("l_regressive_v", "l_regressive_v"),
            ("l_unpronouncable", "l_unpronouncable"),
            ("l_sonorant_min", "l_sonorant_min"),
        ):
            check = _checkRow(panel, self, _("Enable {label}").format(label=label), False)
            s.Add(check, 0, wx.BOTTOM, 3)
            row, ctrl = _numericCombo(panel, self, _("{label} value:").format(label=label), 0, -10000, 10000, 1, 10)
            s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
            self._internalOptionControls[key] = (check, ctrl)
            self._numericControls.append(ctrl)

        self.fastOverride = _checkRow(panel, self, _("Enable fast_test2"), False)
        s.Add(self.fastOverride, 0, wx.BOTTOM, 3)
        row, self.fastValue = _numericCombo(panel, self, _("Fast test2:"), 449, 0, 2000, 1, 50)
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 8)
        self._numericControls.append(self.fastValue)

        self.mbrolaOverride = _checkRow(panel, self, _("Enable MBROLA backend"), False)
        s.Add(self.mbrolaOverride, 0, wx.BOTTOM, 4)
        row, self.mbrolaVoiceText = _textRow(panel, self, _("MBROLA voice:"))
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4)
        row, self.mbrolaPhonemesText = _textRow(panel, self, _("MBROLA phoneme translation:"))
        s.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4)
        row, self.mbrolaSampleRate = _numericCombo(panel, self, _("MBROLA sample rate:"), 16000, 8000, 96000, 100, 1000)
        s.Add(row, 0, wx.EXPAND)
        self._numericControls.append(self.mbrolaSampleRate)

    def _helpLanguage(self):
        try:
            language = str(languageHandler.getLanguage() or "en").replace("-", "_").split("_", 1)[0].casefold()
        except Exception:
            language = "en"
        return language if language in ("en", "it", "es", "fr") else "en"

    def _onHelp(self, evt=None):
        try:
            addonRoot = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            path = os.path.join(addonRoot, "doc", self._helpLanguage(), "readme.html")
            if not os.path.isfile(path):
                path = os.path.join(addonRoot, "doc", "en", "readme.html")
            if not os.path.isfile(path):
                raise RuntimeError(_("Help file not found."))
            os.startfile(path)
        except Exception as e:
            ui.message(_("Unable to open help: {error}").format(error=e))

    def _bindAccelerators(self):
        previewId = int(wx.NewIdRef())
        saveId = int(wx.NewIdRef())
        installId = int(wx.NewIdRef())
        resetId = int(wx.NewIdRef())
        sectionId = int(wx.NewIdRef())
        variantsId = int(wx.NewIdRef())
        parametersId = int(wx.NewIdRef())
        previewTextId = int(wx.NewIdRef())
        variantNameId = int(wx.NewIdRef())
        helpId = int(wx.NewIdRef())
        entries = [
            (wx.ACCEL_ALT, ord("P"), previewId),
            (wx.ACCEL_CTRL, ord("S"), saveId),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("S"), installId),
            (wx.ACCEL_ALT, ord("I"), resetId),
            (wx.ACCEL_CTRL, wx.WXK_DELETE, resetId),
            (wx.ACCEL_ALT, ord("S"), sectionId),
            (wx.ACCEL_ALT, ord("V"), variantsId),
            (wx.ACCEL_ALT, ord("L"), parametersId),
            (wx.ACCEL_ALT, ord("E"), previewTextId),
            (wx.ACCEL_ALT, ord("N"), variantNameId),
            (wx.ACCEL_ALT, ord("H"), helpId),
        ]
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))
        self.Bind(wx.EVT_MENU, lambda evt: self._preview(), id=previewId)
        self.Bind(wx.EVT_MENU, self._onSave, id=saveId)
        self.Bind(wx.EVT_MENU, self._onInstallInNvda, id=installId)
        self.Bind(wx.EVT_MENU, self._onRestoreVariant, id=resetId)
        self.Bind(wx.EVT_MENU, lambda evt: self.sectionChoice.SetFocus(), id=sectionId)
        self.Bind(wx.EVT_MENU, lambda evt: self._cycleVariantSelectorFocus(), id=variantsId)
        self.Bind(wx.EVT_MENU, lambda evt: self._focusFirstInCurrentSection(), id=parametersId)
        self.Bind(wx.EVT_MENU, lambda evt: self.previewText.SetFocus(), id=previewTextId)
        self.Bind(wx.EVT_MENU, lambda evt: self.variantName.SetFocus(), id=variantNameId)
        self.Bind(wx.EVT_MENU, self._onHelp, id=helpId)

    def _recordById(self, recordId):
        return next((r for r in self._variantRecords if r.get("id") == recordId), None)

    def _sourceStateForLanguage(self, baseVoice):
        """Build the selected source variant on top of one specific language.

        This is deliberately independent from the Ctrl+Delete baseline.  It gives
        language switching a clean reference so defaults from language A never
        become accidental variant overrides after moving to language B.
        """
        record = self._recordById(self._selectedVariantId)
        if record is None or record.get("id") == _NEW_VARIANT_ID:
            record = self._recordById("none")
        path = record.get("path") if record else None
        return _effectiveVoiceState(baseVoice, path)

    def _clearNativeVariantChoice(self):
        """Leave the native source picker with no current selection."""
        try:
            self.variantCombo.SetSelection(wx.NOT_FOUND)
            self.variantCombo._esvdLastInitial = None
        except Exception:
            pass

    def _selectVariantChoices(self, selectedId=None):
        """Reflect the exact clean source while it is still unmodified."""
        wanted = selectedId or self._selectedVariantId or "none"
        # The standard voice is the native source with id ``none``.  Treat it
        # exactly like native:m1/native:f2/etc. while it is still clean.  TEST40
        # accidentally cleared the Choice after loading ``none``; wx.Choice with
        # no selection then ignored Up/Down until Home/End/PageUp/PageDown seeded
        # a real index.  Keeping ``none`` selected makes normal arrow browsing
        # continue directly from the standard voice.
        nativeCleanSource = str(wanted) == "none" or str(wanted).startswith("native:")
        if not self._isNewVariant and nativeCleanSource:
            self._setChoice(self.variantCombo, wanted)
            self._setChoice(self.savedVariantCombo, _NEW_VARIANT_ID)
        elif not self._isNewVariant and str(wanted).startswith("user:"):
            self._clearNativeVariantChoice()
            self._setChoice(self.savedVariantCombo, wanted)
        else:
            self._clearNativeVariantChoice()
            self._setChoice(self.savedVariantCombo, _NEW_VARIANT_ID)
        return wanted

    def _refreshVariantChoices(self, selectedId=None):
        """Rebuild the two libraries only after the files themselves changed."""
        self._variantRecords = _allVariantRecords(self._synth)

        stockChoices = _stockVariantChoices(self._variantRecords)
        self.variantCombo.Clear()
        self.variantCombo._esvdChoices = list(stockChoices)
        for label, _value in stockChoices:
            self.variantCombo.Append(label)

        savedChoices = _savedVariantChoices(self._variantRecords)
        self.savedVariantCombo.Clear()
        self.savedVariantCombo._esvdChoices = list(savedChoices)
        for label, _value in savedChoices:
            self.savedVariantCombo.Append(label)

        return self._selectVariantChoices(selectedId)

    def _loadValuesIntoControls(self, values):
        self._linkedCanonicalValues.clear()
        self._setChoice(self.genderCombo, values["gender"])
        self._setChoice(self.clarity, int(values.get("clarity", 4)))
        for ctrl, key in (
            (self.age, "age"),
            (self.pitchBase, "pitchBase"), (self.pitchRange, "pitchRange"),
            (self.voicing, "voicing"), (self.consonantUnvoiced, "consonantUnvoiced"),
            (self.consonantVoiced, "consonantVoiced"), (self.roughness, "roughness"),
            (self.flutter, "flutter"), (self.speed, "speed"),
            (self.echoDelay, "echoDelay"), (self.echoAmp, "echoAmp"),
            (self.fastValue, "fastValue"),
            (self.mbrolaSampleRate, "mbrolaSampleRate"),
        ):
            self._setCtrl(ctrl, values[key])
        for i, ctrls in enumerate(self._formantControls):
            for j, ctrl in enumerate(ctrls):
                self._setCtrl(ctrl, values["formants"][i][j])
        for i, ctrl in enumerate(self._breathControls):
            self._setCtrl(ctrl, values["breath"][i])
        for i, ctrl in enumerate(self._breathWControls):
            self._setCtrl(ctrl, values["breathw"][i])
        self._setChoice(self.toneCountCombo, values["toneCount"])
        for i, pair in enumerate(self._toneControls):
            self._setCtrl(pair[0], values["tone"][i][0])
            self._setCtrl(pair[1], values["tone"][i][1])
        self._resetToneMacros(values)
        self._setChoice(self.klattSourceCombo, values["klattSource"])

        for (i, _name), c in zip(_STRESS_VISIBLE, self._stressLengthControls):
            self._setCtrl(c, values["stressLength"][i])
        for (i, _name), c in zip(_STRESS_VISIBLE, self._stressAddControls):
            self._setCtrl(c, values["stressAdd"][i])
        for (i, _name), c in zip(_STRESS_VISIBLE, self._stressAmpControls):
            self._setCtrl(c, values["stressAmp"][i])
        self.maintainerText.ChangeValue(str(values.get("maintainer", "")))
        self._setChoice(self.statusCombo, values.get("status", ""))
        self.metaDescriptionText.ChangeValue(str(values.get("metaDescription", "")))
        self.metaVersionText.ChangeValue(str(values.get("metaVersion", "")))
        self.metaLicenseText.ChangeValue(str(values.get("metaLicense", "")))
        self.metaContactText.ChangeValue(str(values.get("metaContact", "")))

        for key, (check, ctrl) in self._internalOptionControls.items():
            enabled, val = values.get("internalOptions", {}).get(key, [False, 0])
            check.SetValue(bool(enabled))
            self._setCtrl(ctrl, val)
        self.fastOverride.SetValue(bool(values.get("fastOverride")))
        self.mbrolaOverride.SetValue(bool(values.get("mbrolaOverride")))
        self.mbrolaVoiceText.ChangeValue(str(values.get("mbrolaVoice", "")))
        self.mbrolaPhonemesText.ChangeValue(str(values.get("mbrolaPhonemes", "")))
        self._resetConsonantMacros(values)
        self._updatePitchDerivedControls(source="raw")
        self._syncAllLinkedNumeric()
        self._captureKlattDampingAnchors(values)

    def _presentAgainst(self, values, referenceValues, referencePresent):
        """Return source directives plus fields changed from a supplied reference."""
        present = set(referencePresent or ())
        baseline = referenceValues
        groups = {
            "gender": lambda v: (v.get("gender"), int(v.get("age", 0))),
            "pitch": lambda v: (int(v.get("pitchBase", 82)), int(v.get("pitchRange", 118))),
            "voicing": lambda v: int(v.get("voicing", 100)),
            "consonants": lambda v: (int(v.get("consonantUnvoiced", 90)), int(v.get("consonantVoiced", 100))),
            "roughness": lambda v: int(v.get("roughness", 2)),
            "flutter": lambda v: int(v.get("flutter", 2)),
            "clarity": lambda v: int(v.get("clarity", 4)),
            "echo": lambda v: (int(v.get("echoDelay", 0)), int(v.get("echoAmp", 0))),
            "speed": lambda v: int(v.get("speed", 100)),
            "breath": lambda v: tuple(v.get("breath", [])),
            "breathw": lambda v: tuple(v.get("breathw", [])),
            "tone": lambda v: (int(v.get("toneCount", 4)), tuple(tuple(x) for x in v.get("tone", []))),
            "klatt": lambda v: int(v.get("klattSource", 0)),
            "words": lambda v: (int(v.get("wordGap", 0)), int(v.get("vowelPause", 0))),
            "intonation": lambda v: int(v.get("intonation", 0)),
            "stressLength": lambda v: tuple(v.get("stressLength", [])),
            "stressAdd": lambda v: tuple(v.get("stressAdd", [])),
            "stressAmp": lambda v: tuple(v.get("stressAmp", [])),
            "stressRule": lambda v: tuple(v.get("stressRule", [])),
            "brackets": lambda v: int(v.get("brackets", 4)),
            "bracketsAnnounced": lambda v: int(v.get("bracketsAnnounced", 2)),
            "lowercaseSentence": lambda v: bool(v.get("lowercaseSentence")),
            "spellingStress": lambda v: bool(v.get("spellingStress")),
            "phonemes": lambda v: str(v.get("phonemes", "")).strip(),
            "dictionary": lambda v: str(v.get("dictionary", "")).strip(),
            "dictrules": lambda v: tuple(_parseIntList(v.get("dictrules"), 0, 31)),
            "stressOpt": lambda v: tuple(_parseIntList(v.get("stressOpt"), 0, 31)),
            "numbers": lambda v: tuple(_parseIntList(v.get("numbers"), 1, 63)),
            "tunes": lambda v: str(v.get("tunes", "")).strip(),
            "replace": lambda v: tuple(_normalizeRawLines(v.get("replacements", ""), "replace")),
            "dictMin": lambda v: (bool(v.get("dictMinOverride")), int(v.get("dictMin", 0))),
            "fast": lambda v: (bool(v.get("fastOverride")), int(v.get("fastValue", 449))),
            "mbrola": lambda v: (bool(v.get("mbrolaOverride")), str(v.get("mbrolaVoice", "")).strip(), str(v.get("mbrolaPhonemes", "")).strip(), int(v.get("mbrolaSampleRate", 16000))),
            "maintainer": lambda v: str(v.get("maintainer", "")).strip(),
            "status": lambda v: str(v.get("status", "")).strip(),
            "metaDescription": lambda v: str(v.get("metaDescription", "")).strip(),
            "metaVersion": lambda v: str(v.get("metaVersion", "")).strip(),
            "metaLicense": lambda v: str(v.get("metaLicense", "")).strip(),
            "metaContact": lambda v: str(v.get("metaContact", "")).strip(),
            "variants": lambda v: (bool(v.get("variantsOverride")), int(v.get("variants", 4))),
        }
        for i in range(9):
            groups[f"formant:{i}"] = lambda v, index=i: tuple(v.get("formants", [])[index])
        for key in self._internalOptionControls.keys():
            groups[key] = lambda v, k=key: tuple(v.get("internalOptions", {}).get(k, [False, 0]))
        for key, getter in groups.items():
            try:
                changed = getter(values) != getter(baseline)
            except Exception:
                changed = False
            if changed:
                present.add(key)
            elif key not in set(referencePresent or ()):
                present.discard(key)

        # `breath` and `breathw` are especially audible and sparse in native
        # eSpeak variants.  If the source did not contain one of these
        # directives, never invent it because of control normalization or a
        # mirrored Klatt control while the user is editing something unrelated.
        # It becomes eligible only after the corresponding control family has
        # actually been touched.
        sourcePresent = set(referencePresent or ())
        touched = set(getattr(self, "_sparseDirectiveTouched", set()))
        for sparseKey in ("breath", "breathw"):
            if sparseKey not in sourcePresent and sparseKey not in touched:
                present.discard(sparseKey)
        return present

    def _effectivePresent(self, values):
        """Directives to save: selected source plus real user edits.

        Compare against the selected source rendered in the current language,
        never against the language in which the project originally started.
        """
        referenceValues = getattr(self, "_languageReferenceValues", self._baselineValues)
        referencePresent = getattr(self, "_languageReferencePresent", self._baselinePresent)
        return self._presentAgainst(values, referenceValues, referencePresent)

    def _runtimePresent(self, values):
        # SetVoiceByFile needs a full voice, but a true !v variant is applied
        # after VoiceReset(2). Do not leak timbral language-voice attributes
        # into a variant-derived runtime; only language/prosody state survives.
        languagePresent = set(self._languagePresent)
        if getattr(self, "_sourceUsesVariantReset", False):
            languagePresent -= set(_VARIANT_RESET_DIRECTIVES)
        return languagePresent | set(self._effectivePresent(values))

    def _onDraftMetadataChanged(self, evt):
        # Preview/name edits do not reload eSpeak, but they are part of the
        # persistent editor draft and therefore update the window state marker.
        self._refreshModifiedTitle()
        evt.Skip()

    def _isSavedPersonalSource(self):
        """Return True only while the current source is a saved personal variant."""
        return str(getattr(self, "_selectedVariantId", "")).startswith("user:")

    def _isModifiedState(self):
        """Return the user-visible draft/install state.

        Only a saved personal variant that still exactly matches its saved base
        is considered clean. Native/factory eSpeak variants (including the
        standard voice) deliberately start as Modified so they must first pass
        through Ctrl+S into the personal library before Ctrl+Shift+S can install
        a copy back into NVDA.
        """
        if not self._isSavedPersonalSource():
            return True
        return self._hasDraftContent()

    def _refreshModifiedTitle(self):
        """Show literal English 'Modified' whenever the current state is not installable."""
        baseTitle = f"{ADDON_TITLE} - {TEST_LABEL}"
        try:
            modified = self._isModifiedState()
        except Exception:
            modified = True
        title = f"{baseTitle} - Modified" if modified else baseTitle
        try:
            if self.GetTitle() != title:
                self.SetTitle(title)
        except Exception:
            pass

    def _voiceStateChanged(self, values=None):
        if values is None:
            values = self._readControls()
        if str(self._baseVoice) != str(self._baselineVoice):
            return True
        # Reuse directive-aware comparison and also catch booleans/fields that
        # can return to the exact baseline value.
        present = self._effectivePresent(values)
        if present != set(self._baselinePresent):
            return True
        try:
            return values != self._baselineValues
        except Exception:
            return True

    def _updateVariantIndicators(self, values=None):
        # Keep a source selector selected only while the controls still match that
        # exact source. The first real edit turns the project into a new variant
        # and clears the native selector; this also makes keyboard browsing of
        # native variants continuous and predictable.
        if self._voiceStateChanged(values):
            self._isNewVariant = True
        elif self._showSourceWhenClean:
            self._isNewVariant = False
        else:
            self._isNewVariant = True
        self._selectVariantChoices(self._selectedVariantId)

    def _loadVariantRecord(self, record, announce=True):
        if record is None:
            record = self._recordById("none")
        if record is None:
            return

        # Saved projects carry their target language. Native NVDA/eSpeak variants are
        # applied to the language currently selected in the language combo.
        if record.get("kind") == "user":
            savedLanguage = str(record.get("language", "") or "")
            if savedLanguage:
                self._baseVoice = savedLanguage
                self._setChoice(self.languageCombo, self._baseVoice)

        nativeDirect = record.get("kind") == "native"
        if nativeDirect:
            # Crucial TEST36 behavior: load the real installed NVDA/eSpeak
            # variant first. Do not reconstruct it from the voice that happened
            # to be active when the Designer opened.
            _setNativeVoiceAndVariantNow(self._baseVoice, record.get("variantId", record.get("name", "none")))
            _discardRuntimeVoiceFile()

        (
            values,
            present,
            displayName,
            self._languageValues,
            self._languagePresent,
        ) = _effectiveVoiceState(self._baseVoice, record.get("path"))
        self._selectedVariantId = record.get("id", "none")
        self._selectedVariantFileName = str(record.get("name", "none"))
        self._selectedVariantDisplayName = displayName
        self._sourceVariantPath = record.get("path")
        self._sourceVariantText = _readVoiceText(self._sourceVariantPath)
        self._sourceUsesVariantReset = bool(self._sourceVariantPath)
        self._baselineVoice = self._baseVoice
        self._baselineValues = copy.deepcopy(values)
        self._baselinePresent = set(present)
        self._languageReferenceValues = copy.deepcopy(values)
        self._languageReferencePresent = set(present)
        self._values = copy.deepcopy(values)
        # A native NVDA/eSpeak variant remains visibly selected while it is still
        # untouched. The first parameter edit clears that selector and turns the
        # work into an unsaved new variant. Ctrl+Delete keeps this clean source as
        # its baseline in either case. Saved personal variants behave likewise.
        self._showSourceWhenClean = True
        self._isNewVariant = False
        self._sparseDirectiveTouched.clear()

        self._loadValuesIntoControls(values)
        self._loadEditorSidecarForRecord(record, values)
        self._sourcePatchBaselineValues = copy.deepcopy(self._readControls())
        # The library has not changed: do not rebuild selectors while handling
        # their event. Keep the exact clean source selected until the first edit.
        self._selectVariantChoices(self._selectedVariantId)
        saveName = self._selectedVariantFileName if self._selectedVariantId != "none" else "new-variant"
        self.variantName.ChangeValue(saveName)
        self._draftBaselineVariantName = str(saveName)
        self._draftBaselinePreviewText = str(self.previewText.GetValue())
        self._refreshModifiedTitle()
        self._nativeDirectActive = nativeDirect
        if not nativeDirect:
            self._applyNow(markDirty=False, immediate=True)
        if announce:
            label = displayName if self._selectedVariantId != "none" else _("standard voice")
            ui.message(_("Variant {name} loaded").format(name=label))

    def _onVariantChanged(self, evt):
        recordId = _choiceValue(self.variantCombo, None)
        if not recordId:
            evt.Skip()
            return
        # Choosing a different source variant intentionally abandons any old
        # persistent draft. The newly selected variant becomes the new base.
        if str(recordId) != str(self._selectedVariantId):
            _deleteDraftState()
        self._setChoice(self.savedVariantCombo, _NEW_VARIANT_ID)
        self._loadVariantRecord(self._recordById(str(recordId)), announce=True)
        # Keep this native variant selected while it is still untouched. The first
        # parameter edit will clear the selector automatically.
        evt.Skip()

    def _onSavedVariantChanged(self, evt):
        recordId = str(_choiceValue(self.savedVariantCombo, _NEW_VARIANT_ID))
        if recordId != str(self._selectedVariantId):
            _deleteDraftState()
        if recordId == _NEW_VARIANT_ID:
            self._isNewVariant = True
            self._clearNativeVariantChoice()
            evt.Skip()
            return
        self._loadVariantRecord(self._recordById(recordId), announce=True)
        evt.Skip()

    def _renameSelectedSavedVariant(self):
        """Rename only a user-saved variant file (F2 on Saved variants)."""
        recordId = str(_choiceValue(self.savedVariantCombo, _NEW_VARIANT_ID))
        if recordId == _NEW_VARIANT_ID:
            ui.message(_("Select a saved variant to rename first"))
            return
        record = self._recordById(recordId)
        if not record or record.get("kind") != "user" or not record.get("path"):
            ui.message(_("F2 renames only saved variants, not NVDA eSpeak variants"))
            return

        oldPath = str(record["path"])
        oldFileName = str(record.get("name", os.path.basename(oldPath)))
        dlg = wx.TextEntryDialog(
            self,
            _("New file name for the saved variant:"),
            _("Rename saved variant"),
            value=oldFileName,
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            requested = str(dlg.GetValue()).strip()
        finally:
            dlg.Destroy()

        if not requested:
            ui.message(_("The name cannot be empty"))
            return
        newFileName = _safeFileName(requested)
        newPath = os.path.join(os.path.dirname(oldPath), newFileName)
        if os.path.normcase(os.path.abspath(newPath)) == os.path.normcase(os.path.abspath(oldPath)):
            self.variantName.ChangeValue(newFileName)
            ui.message(_("The variant is already named {name}").format(name=newFileName))
            return
        if os.path.exists(newPath):
            ui.message(_("A saved variant named {name} already exists").format(name=newFileName))
            return

        try:
            # Keep the eSpeak internal name consistent with the renamed file so
            # later native installation and external inspection do not retain
            # the old name. Preserve every other directive byte-for-byte as text.
            text = None
            usedEncoding = "utf-8"
            for encoding in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    with open(oldPath, "r", encoding=encoding) as f:
                        text = f.read()
                    usedEncoding = "utf-8"
                    break
                except UnicodeDecodeError:
                    continue
            if text is None:
                raise RuntimeError(_("Unable to read the variant file"))
            replacement = f"name {_safeFileName(newFileName).replace(' ', '_')}"
            lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            replaced = False
            for i, raw in enumerate(lines):
                stripped = raw.strip()
                if stripped and not stripped.startswith(("//", "#")) and stripped.split(None, 1)[0].casefold() == "name":
                    prefix = raw[:len(raw) - len(raw.lstrip())]
                    lines[i] = prefix + replacement
                    replaced = True
                    break
            if not replaced:
                insertAt = 0
                for i, raw in enumerate(lines):
                    if raw.strip().casefold() == "language variant":
                        insertAt = i + 1
                        break
                lines.insert(insertAt, replacement)
            _writeTextAtomic(newPath, "\r\n".join(lines))
            os.remove(oldPath)
            oldSidecar = _editorSidecarPath(oldPath)
            newSidecar = _editorSidecarPath(newPath)
            if os.path.exists(oldSidecar):
                os.replace(oldSidecar, newSidecar)

            language = str(record.get("language", "") or _safeFileName(self._baseVoice))
            newId = f"user:{language}:{newFileName}"
            self._selectedVariantId = newId
            self._selectedVariantFileName = newFileName
            self._selectedVariantDisplayName = newFileName
            self.variantName.ChangeValue(newFileName)
            # Renaming does not change the sound/baseline and must not turn the
            # project into a new variant. Rebuild because the library changed.
            self._showSourceWhenClean = True
            self._isNewVariant = False
            self._draftBaselineVariantName = str(newFileName)
            self._refreshVariantChoices(newId)
            self._refreshModifiedTitle()
            wx.CallAfter(self.savedVariantCombo.SetFocus)
            ui.message(_("Variant renamed to {name}").format(name=newFileName))
        except Exception as e:
            log.error("eSpeak Voice Designer: unable to rename saved variant", exc_info=True)
            ui.message(_("Unable to rename the variant: {error}").format(error=e))

    def _deleteSelectedSavedVariant(self):
        """Delete only the selected user-saved variant after confirmation.

        The current sound is deliberately kept in memory as a new unsaved
        variant, so deleting a personal file never changes what the user is
        hearing.  The optional editor sidecar is removed with the voice file.
        """
        recordId = str(_choiceValue(self.savedVariantCombo, _NEW_VARIANT_ID))
        if recordId == _NEW_VARIANT_ID:
            ui.message(_("Select a saved variant to delete first"))
            return
        record = self._recordById(recordId)
        if not record or record.get("kind") != "user" or not record.get("path"):
            ui.message(_("Delete only removes saved personal variants"))
            return

        path = str(record["path"])
        fileName = str(record.get("name", os.path.basename(path)))
        confirm = wx.MessageDialog(
            self,
            _("Permanently delete the personal variant {name}?").format(name=fileName),
            _("Delete saved variant"),
            style=wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        try:
            if confirm.ShowModal() != wx.ID_YES:
                ui.message(_("Deletion cancelled"))
                return
        finally:
            confirm.Destroy()

        try:
            # Capture exactly what is sounding before removing the backing file.
            currentValues = self._readControls()
            currentPresent = self._effectivePresent(currentValues)
            if os.path.exists(path):
                os.remove(path)
            sidecar = _editorSidecarPath(path)
            if os.path.exists(sidecar):
                os.remove(sidecar)

            # Keep the sound/editor state, but it is no longer backed by a saved
            # personal file. Ctrl+Delete restores this in-memory base; Ctrl+S
            # can recreate it under the same or a different name.
            self._selectedVariantId = "none"
            self._selectedVariantFileName = fileName
            self._selectedVariantDisplayName = _NEW_VARIANT_LABEL
            self._baselineVoice = self._baseVoice
            self._baselineValues = copy.deepcopy(currentValues)
            self._baselinePresent = set(currentPresent)
            self._languageReferenceValues = copy.deepcopy(currentValues)
            self._languageReferencePresent = set(currentPresent)
            self._values = copy.deepcopy(currentValues)
            self._showSourceWhenClean = False
            self._isNewVariant = True
            # Preserve the old filename in the save-name field for convenient
            # recreation, while both variant libraries visibly return to New.
            self.variantName.ChangeValue(fileName)
            self._refreshVariantChoices(_NEW_VARIANT_ID)
            self._clearNativeVariantChoice()
            self._setChoice(self.savedVariantCombo, _NEW_VARIANT_ID)
            wx.CallAfter(self.savedVariantCombo.SetFocus)
            ui.message(_("Variant {name} deleted. The current voice remains as a New variant").format(name=fileName))
        except Exception as e:
            log.error("eSpeak Voice Designer: unable to delete saved variant", exc_info=True)
            ui.message(_("Unable to delete the variant: {error}").format(error=e))

    def _onRestoreVariant(self, evt):
        self._baseVoice = self._baselineVoice
        self._setChoice(self.languageCombo, self._baseVoice)
        languagePath = _languageFileForVoice(self._baseVoice)
        if languagePath:
            self._languageValues, self._languagePresent, _languageDisplayName = _readVariantFile(languagePath)
        else:
            self._languageValues, self._languagePresent = copy.deepcopy(_DEFAULT_VALUES), set()
        self._values = copy.deepcopy(self._baselineValues)
        self._languageReferenceValues = copy.deepcopy(self._baselineValues)
        self._languageReferencePresent = set(self._baselinePresent)
        self._loadValuesIntoControls(self._values)
        self._loadEditorSidecarForRecord(self._recordById(self._selectedVariantId), self._values)
        self._sourcePatchBaselineValues = copy.deepcopy(self._readControls())
        self._isNewVariant = not self._showSourceWhenClean
        self._refreshVariantChoices(self._selectedVariantId)
        restoreRecord = self._recordById(self._selectedVariantId)
        if restoreRecord and restoreRecord.get("kind") == "native":
            _setNativeVoiceAndVariantNow(self._baseVoice, restoreRecord.get("variantId", restoreRecord.get("name", "none")))
            _discardRuntimeVoiceFile()
            self._nativeDirectActive = True
        else:
            self._applyNow(markDirty=False, immediate=True)
        self._refreshModifiedTitle()
        label = self._selectedVariantDisplayName if self._selectedVariantId != "none" else _("current / standard voice")
        ui.message(_("Restored {name}").format(name=label))

    def _onLanguageChanged(self, evt):
        # If a clean installed NVDA/eSpeak variant is selected, language is a
        # source selector too: load the real voice+variant directly and rebuild
        # the controls from that clean source. This avoids manufacturing a
        # runtime voice merely because the language changed.
        targetVoice = str(_choiceValue(self.languageCombo, self._baseVoice))
        selectedRecord = self._recordById(self._selectedVariantId)
        if selectedRecord and selectedRecord.get("kind") == "native" and not self._isNewVariant:
            self._baseVoice = targetVoice
            _setNativeVoiceAndVariantNow(
                self._baseVoice,
                selectedRecord.get("variantId", selectedRecord.get("name", "none")),
            )
            _discardRuntimeVoiceFile()
            (
                values,
                present,
                displayName,
                self._languageValues,
                self._languagePresent,
            ) = _effectiveVoiceState(self._baseVoice, selectedRecord.get("path"))
            self._baselineVoice = self._baseVoice
            self._baselineValues = copy.deepcopy(values)
            self._baselinePresent = set(present)
            self._languageReferenceValues = copy.deepcopy(values)
            self._languageReferencePresent = set(present)
            self._values = copy.deepcopy(values)
            self._selectedVariantDisplayName = displayName
            self._sourceVariantPath = selectedRecord.get("path")
            self._sourceVariantText = _readVoiceText(self._sourceVariantPath)
            self._sourceUsesVariantReset = bool(self._sourceVariantPath)
            self._showSourceWhenClean = True
            self._nativeDirectActive = True
            self._loadValuesIntoControls(values)
            self._sourcePatchBaselineValues = copy.deepcopy(self._readControls())
            self._selectVariantChoices(self._selectedVariantId)
            evt.Skip()
            return

        # Otherwise preserve only the selected source and genuine user edits.
        # Never preserve defaults inherited from the language being left.
        currentValues = self._readControls()
        activePresent = self._effectivePresent(currentValues)

        overlayValues = copy.deepcopy(currentValues)
        # extraLines are not represented in the directive set. Remove every
        # line that belongs to the current language+source reference, leaving
        # only extra lines genuinely added while editing. The new language and
        # source will contribute their own extras below.
        referenceExtras = list(getattr(self, "_languageReferenceValues", {}).get("extraLines", []) or [])
        editedExtras = list(overlayValues.get("extraLines", []) or [])
        for line in referenceExtras:
            try:
                editedExtras.remove(line)
            except ValueError:
                pass
        overlayValues["extraLines"] = editedExtras

        self._baseVoice = targetVoice
        (
            sourceValues,
            sourcePresent,
            _sourceName,
            self._languageValues,
            self._languagePresent,
        ) = self._sourceStateForLanguage(self._baseVoice)

        # This clean source state becomes the reference for the next language
        # change. User edits are layered on top but are not folded into it.
        self._languageReferenceValues = copy.deepcopy(sourceValues)
        self._languageReferencePresent = set(sourcePresent)
        self._values = _overlayValues(sourceValues, overlayValues, activePresent)
        self._loadValuesIntoControls(self._values)
        self._applyBeforeAnnouncement()
        evt.Skip()

    def _readControls(self):
        values = copy.deepcopy(self._values)
        self._baseVoice = str(_choiceValue(self.languageCombo, self._baseVoice))
        values["gender"] = _choiceValue(self.genderCombo, values["gender"])
        values["age"] = _numericValue(self.age, values["age"])
        values["pitchBase"] = _numericValue(self.pitchBase, values["pitchBase"])
        values["pitchRange"] = _numericValue(self.pitchRange, values["pitchRange"])
        values["voicing"] = _numericValue(self.voicing, values["voicing"])
        values["consonantUnvoiced"] = _numericValue(self.consonantUnvoiced, values["consonantUnvoiced"])
        values["consonantVoiced"] = _numericValue(self.consonantVoiced, values["consonantVoiced"])
        values["roughness"] = _numericValue(self.roughness, values["roughness"])
        values["flutter"] = _numericValue(self.flutter, values["flutter"])
        values["clarity"] = int(_choiceValue(self.clarity, values.get("clarity", 4)))
        values["speed"] = _numericValue(self.speed, values["speed"])
        values["echoDelay"] = _numericValue(self.echoDelay, values["echoDelay"])
        values["echoAmp"] = _numericValue(self.echoAmp, values["echoAmp"])

        values["formants"] = [
            [_numericValue(ctrls[j], values["formants"][i][j]) for j in range(4)]
            for i, ctrls in enumerate(self._formantControls)
        ]
        values["breath"] = [_numericValue(c, values["breath"][i]) for i, c in enumerate(self._breathControls)]
        values["breathw"] = [_numericValue(c, values["breathw"][i]) for i, c in enumerate(self._breathWControls)]
        values["toneCount"] = int(_choiceValue(self.toneCountCombo, values["toneCount"]))
        values["tone"] = [[_numericValue(pair[0], values["tone"][i][0]), _numericValue(pair[1], values["tone"][i][1])] for i, pair in enumerate(self._toneControls)]

        values["klattSource"] = int(_choiceValue(self.klattSourceCombo, values.get("klattSource", 0)))

        stressLength = list(values["stressLength"])
        stressAdd = list(values["stressAdd"])
        stressAmp = list(values["stressAmp"])
        for (i, _name), c in zip(_STRESS_VISIBLE, self._stressLengthControls):
            stressLength[i] = _numericValue(c, stressLength[i])
        for (i, _name), c in zip(_STRESS_VISIBLE, self._stressAddControls):
            stressAdd[i] = _numericValue(c, stressAdd[i])
        for (i, _name), c in zip(_STRESS_VISIBLE, self._stressAmpControls):
            stressAmp[i] = _numericValue(c, stressAmp[i])
        values["stressLength"] = stressLength
        values["stressAdd"] = stressAdd
        values["stressAmp"] = stressAmp
        values["internalOptions"] = {}
        for key, (check, ctrl) in self._internalOptionControls.items():
            values["internalOptions"][key] = [check.GetValue(), _numericValue(ctrl, 0)]
        values["fastOverride"] = self.fastOverride.GetValue()
        values["fastValue"] = _numericValue(self.fastValue, values["fastValue"])
        values["mbrolaOverride"] = self.mbrolaOverride.GetValue()
        values["mbrolaVoice"] = self.mbrolaVoiceText.GetValue().strip()
        values["mbrolaPhonemes"] = self.mbrolaPhonemesText.GetValue().strip()
        values["mbrolaSampleRate"] = _numericValue(self.mbrolaSampleRate, values["mbrolaSampleRate"])

        values["maintainer"] = self.maintainerText.GetValue().strip()
        values["status"] = _choiceValue(self.statusCombo, "")
        values["metaDescription"] = self.metaDescriptionText.GetValue().strip()
        values["metaVersion"] = self.metaVersionText.GetValue().strip()
        values["metaLicense"] = self.metaLicenseText.GetValue().strip()
        values["metaContact"] = self.metaContactText.GetValue().strip()
        # Duplicated controls (Formants/Klatt, Voicing, Flutter, Breath) are
        # resolved from their canonical value last.  This guarantees that the
        # two UI sections always serialize and sound identically.
        self._applyCanonicalLinkedValues(values)
        return values

    def _applyBeforeAnnouncement(self):
        """Commit a discrete UI change before NVDA announces its new value."""
        if self._applyTimer is not None:
            try:
                self._applyTimer.Stop()
            except Exception:
                pass
            self._applyTimer = None
        self._applyNow(immediate=True)

    def _scheduleApply(self):
        try:
            values = self._readControls()
            self._updateVariantIndicators(values)
            self._refreshModifiedTitle()
        except Exception:
            values = None
        if self._applyTimer is not None:
            try:
                self._applyTimer.Stop()
            except Exception:
                pass
        self._applyTimer = wx.CallLater(55, self._applyNow)

    def _applyNow(self, markDirty=True, immediate=False):
        try:
            self._nativeDirectActive = False
            self._values = self._readControls()
            if markDirty:
                self._updateVariantIndicators(self._values)
                self._refreshModifiedTitle()
            present = self._runtimePresent(self._values)
            if getattr(self, "_sourceUsesVariantReset", False) and getattr(self, "_sourceVariantText", ""):
                # TEST47 keeps true `language variant` semantics during live
                # editing. Write only a variant file, then ask eSpeak to load
                # baseVoice+thatVariant so LoadVoice(..., control=2) is used.
                path, runtimeVariantSuffix = _runtimeVariantLocation()
                runtimeText = _variantTextFromSource(
                    self._values, "esvd_live", self._baseVoice, self._sourceVariantText,
                    getattr(self, "_sourcePatchBaselineValues", self._baselineValues),
                    self._effectivePresent(self._values), self._baselinePresent,
                )
                _writeTextAtomic(path, runtimeText)
                _queueVoiceVariantLoad(self._baseVoice, runtimeVariantSuffix, immediate=immediate)
            else:
                # The standard (no-variant) voice still uses the established
                # full-file runtime path in this focused experiment.
                path = _runtimeVoicePath()
                runtimeText = _fullVoiceText(self._values, self._baseVoice, runtimeName="esvdtest48", present=present)
                _writeTextAtomic(path, runtimeText)
                if int(self._values.get("klattSource", 0)) == 0:
                    _forceStandardEspeakEngine(self._baseVoice, immediate=immediate)
                _queueVoiceFileLoad(path, immediate=immediate)
        except Exception as e:
            log.error("eSpeak Voice Designer: unable to apply working voice", exc_info=True)
            ui.message(_("eSpeak Voice Designer error: {error}").format(error=e))

    def _contextPreviewText(self):
        try:
            focused = self._normalizeFocusWindow(wx.Window.FindFocus())
            name = str(focused.GetName() or "").casefold() if focused else ""
        except Exception:
            name = ""
        if "parenthesis pause" in name:
            return _("Before the parentheses (this part is in parentheses) after the parentheses.")
        if "lowercase" in name:
            return _("First sentence. second sentence. third sentence.")
        if "abbreviation" in name:
            return "FBI, USB, CPU, HTML."
        if "vowel separation" in name:
            return _("I am going to listen. Here is an example. I am waiting.")
        if "pause between all words" in name:
            return _("This sentence is used to hear the pause between all words.")
        return None

    def _preview(self):
        # Preview must also be transparent when nothing has been edited.  If a
        # typed value is pending or controls differ from the entry baseline,
        # commit that edit first; otherwise simply speak with the current voice.
        try:
            pendingEdit = self._voiceStateChanged(self._readControls())
        except Exception:
            pendingEdit = True
        if pendingEdit:
            self._applyNow()
        text = str(self.previewText.GetValue()).strip() or _DEFAULT_PREVIEW_TEXT
        if text == _DEFAULT_PREVIEW_TEXT:
            text = self._contextPreviewText() or text
        wx.CallAfter(ui.message, text)

    def _setCtrl(self, ctrl, value):
        # Preserve the exact integer from an installed/saved eSpeak source.
        value = _expandNumericRangeForLoadedValue(ctrl, value)
        ctrl._esvdLast = value
        ctrl.ChangeValue(str(value))

    def _setChoice(self, ctrl, value):
        # TEST25 only offers Standard and Klatt 6 for new work. If an older
        # variant contains Klatt 1-5, keep that value representable while the
        # file is open so simply loading it never silently changes its sound.
        if ctrl is getattr(self, "klattSourceCombo", None):
            wanted = int(value)
            choices = list(_KLATT_CHOICES)
            if 1 <= wanted <= 5:
                choices = [
                    _KLATT_CHOICES[0],
                    (_("Klatt {number} legacy - loaded variant only").format(number=wanted), wanted),
                    _KLATT_CHOICES[1],
                ]
            if list(getattr(ctrl, "_esvdChoices", [])) != choices:
                ctrl.Freeze()
                try:
                    ctrl.Clear()
                    for label, _storedValue in choices:
                        ctrl.Append(label)
                    ctrl._esvdChoices = choices
                finally:
                    ctrl.Thaw()
        for i, item in enumerate(ctrl._esvdChoices):
            if item[1] == value:
                ctrl.SetSelection(i)
                return

    def _editorSidecarState(self):
        consonants = copy.deepcopy(getattr(self, "_consonantMacroState", {}))
        if hasattr(self, "consonantStrengthMacro"):
            consonants["strength"] = _numericValue(self.consonantStrengthMacro, 100)
            consonants["balance"] = _numericValue(self.consonantBalanceMacro, 0)
            consonants["body"] = _numericValue(self.consonantBodyMacro, 100)
        toneMacros = copy.deepcopy(getattr(self, "_toneMacroState", {}))
        if hasattr(self, "toneBrightnessMacro"):
            toneMacros["brightness"] = _numericValue(self.toneBrightnessMacro, 0)
            toneMacros["body"] = _numericValue(self.toneBodyMacro, 0)
            toneMacros["presence"] = _numericValue(self.tonePresenceMacro, 0)
        return {
            "consonantMacros": consonants,
            "toneMacros": toneMacros,
            "klattDamping": {
                "value": _numericValue(self.klattDamping, 0) if hasattr(self, "klattDamping") else 0,
                "anchorWidths": list(getattr(self, "_klattDampingAnchorWidths", [100, 100, 100, 100])),
            },
        }

    def _loadEditorSidecarForRecord(self, record, values):
        if not record or record.get("kind") != "user" or not record.get("path"):
            self._resetConsonantMacros(values)
            self._resetToneMacros(values)
            self._captureKlattDampingAnchors(values)
            return
        data = _readEditorSidecar(record.get("path"))
        self._restoreConsonantMacroState(data.get("consonantMacros"), values)
        self._restoreToneMacroState(data.get("toneMacros"), values)
        kd = data.get("klattDamping") if isinstance(data.get("klattDamping"), dict) else {}
        anchors = kd.get("anchorWidths")
        if isinstance(anchors, list) and len(anchors) >= 4:
            try:
                self._klattDampingAnchorWidths = [max(0, min(800, int(x))) for x in anchors[:4]]
            except Exception:
                self._captureKlattDampingAnchors(values)
        else:
            self._captureKlattDampingAnchors(values)
        if hasattr(self, "klattDamping"):
            amount = max(0, min(100, int(kd.get("value", 0) or 0)))
            self._setCtrl(self.klattDamping, amount)

    def _onSave(self, evt):
        """Save to the personal library, always asking for the target name."""
        try:
            self._values = self._readControls()
            fallbackName = self._selectedVariantFileName if self._selectedVariantId != "none" else "new-variant"
            proposedName = str(self.variantName.GetValue()).strip() or fallbackName

            dlg = wx.TextEntryDialog(
                self,
                _("Name to save the variant as. Keep the same name to overwrite, or change it to create a new variant:"),
                _("Save variant as"),
                value=proposedName,
            )
            try:
                # TEST27: wx may reset a TextEntryDialog selection while the
                # modal window is being shown. Select the complete proposed
                # name only after EVT_SHOW, when the real edit control is
                # visible and has focus.
                try:
                    textCtrl = dlg.GetTextCtrl()

                    def _selectSaveNameOnShow(showEvt):
                        showEvt.Skip()
                        if not showEvt.IsShown():
                            return

                        def _selectAll():
                            try:
                                textCtrl.SetFocus()
                                textCtrl.SelectAll()
                            except Exception:
                                pass

                        wx.CallAfter(_selectAll)

                    dlg.Bind(wx.EVT_SHOW, _selectSaveNameOnShow)
                except Exception:
                    pass
                if dlg.ShowModal() != wx.ID_OK:
                    return
                requestedName = str(dlg.GetValue()).strip()
            finally:
                dlg.Destroy()

            if not requestedName:
                ui.message(_("The variant name cannot be empty"))
                return

            name = requestedName
            fileName = _safeFileName(name)
            languageFolder = _safeFileName(self._baseVoice)
            directory = os.path.join(_variantDirectory(), languageFolder)
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, fileName)

            if os.path.exists(path):
                confirm = wx.MessageDialog(
                    self,
                    _("A saved variant named {name} already exists. Do you want to overwrite it?").format(name=fileName),
                    _("Overwrite variant"),
                    style=wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                )
                try:
                    if confirm.ShowModal() != wx.ID_YES:
                        ui.message(_("Save cancelled"))
                        return
                finally:
                    confirm.Destroy()

            present = self._effectivePresent(self._values)
            if getattr(self, "_sourceUsesVariantReset", False) and getattr(self, "_sourceVariantText", ""):
                saveText = _variantTextFromSource(
                    self._values, name, self._baseVoice, self._sourceVariantText,
                    getattr(self, "_sourcePatchBaselineValues", self._baselineValues),
                    present, self._baselinePresent,
                )
            else:
                saveText = _variantText(self._values, name, self._baseVoice, present=present)
            _writeTextAtomic(path, saveText)
            # Editor metadata is deliberately separate. The voice file above is
            # a plain standard eSpeak variant and remains fully usable without
            # this add-on or sidecar.
            _writeEditorSidecar(path, self._editorSidecarState())
            self._sourceVariantPath = path
            self._sourceVariantText = _readVoiceText(path)
            self._sourceUsesVariantReset = True
            self._sourcePatchBaselineValues = copy.deepcopy(self._readControls())

            # The saved file becomes the new current baseline. Therefore Ctrl+Delete
            # restores exactly the version just saved. A changed name creates a
            # new personal variant; the old file is left untouched.
            selectedId = f"user:{languageFolder}:{fileName}"
            self._selectedVariantId = selectedId
            self._selectedVariantFileName = fileName
            self._selectedVariantDisplayName = name
            self.variantName.ChangeValue(fileName)
            self._baselineVoice = self._baseVoice
            self._baselineValues = copy.deepcopy(self._values)
            self._baselinePresent = set(present)
            self._languageReferenceValues = copy.deepcopy(self._values)
            self._languageReferencePresent = set(present)
            # Keep the current editor macro positions as the sidecar baseline.
            # Their baked standard eSpeak values are already in _baselineValues.
            self._showSourceWhenClean = True
            self._isNewVariant = False
            self._refreshVariantChoices(selectedId)
            self._draftBaselineVariantName = str(self.variantName.GetValue())
            self._draftBaselinePreviewText = str(self.previewText.GetValue())
            # The work is now permanent in the personal library; an older
            # continuation draft must not be resurrected on the next opening.
            _deleteDraftState()
            self._refreshModifiedTitle()
            ui.message(_("Variant {name} saved for {language}").format(name=name, language=self._baseVoice))
        except Exception as e:
            log.error("eSpeak Voice Designer: unable to save variant", exc_info=True)
            ui.message(_("Unable to save the variant: {error}").format(error=e))

    def _onInstallInNvda(self, evt):
        """Install only a clean saved personal variant, never a native source or draft."""
        try:
            self._refreshModifiedTitle()
            if self._isModifiedState():
                ui.message(_("The variant is Modified. Save it first with Ctrl+S before installing it in NVDA."))
                return

            self._values = self._readControls()
            fallbackName = self._selectedVariantFileName if self._selectedVariantId != "none" else "new-variant"
            requestedName = str(self.variantName.GetValue()).strip() or fallbackName
            requestedFileName = _safeFileName(requestedName)
            targetDir = _nativeVariantInstallDirectory()
            if not targetDir:
                raise RuntimeError(_("Unable to find the NVDA eSpeak variants folder."))
            if not os.path.isdir(targetDir):
                raise RuntimeError(_("The eSpeak variants folder does not exist: {path}").format(path=targetDir))

            # Ctrl+Shift+S is deliberately non-destructive. If the requested
            # filename already exists (factory or previously installed personal
            # variant), keep it untouched and append a number to the new copy.
            fileName = _availableNativeVariantFileName(targetDir, requestedFileName)
            name = fileName
            renamedForSafety = fileName != requestedFileName

            present = self._effectivePresent(self._values)
            stagingDir = os.path.join(_dataRoot(), "install")
            os.makedirs(stagingDir, exist_ok=True)
            stagingPath = os.path.join(stagingDir, fileName)
            if getattr(self, "_sourceUsesVariantReset", False) and getattr(self, "_sourceVariantText", ""):
                installText = _variantTextFromSource(
                    self._values, name, self._baseVoice, self._sourceVariantText,
                    getattr(self, "_sourcePatchBaselineValues", self._baselineValues),
                    present, self._baselinePresent,
                )
            else:
                installText = _variantText(self._values, name, self._baseVoice, present=present)
            _writeTextAtomic(stagingPath, installText)
            destinationPath = os.path.join(targetDir, fileName)

            # If the installation is writable (portable/non-Protected NVDA), no
            # elevation is needed. Otherwise request UAC through ShellExecuteEx.
            try:
                shutil.copy2(stagingPath, destinationPath)
            except PermissionError:
                ui.message(_("Confirm administrator access to install the variant in NVDA."))
                _elevatedCopyFile(
                    stagingPath,
                    destinationPath,
                    lambda success, error: self._finishNativeInstall(success, error, name, fileName, destinationPath, renamedForSafety),
                )
                return
            except OSError as e:
                if getattr(e, "winerror", None) in (5, 1314):
                    ui.message(_("Confirm administrator access to install the variant in NVDA."))
                    _elevatedCopyFile(
                        stagingPath,
                        destinationPath,
                        lambda success, error: self._finishNativeInstall(success, error, name, fileName, destinationPath, renamedForSafety),
                    )
                    return
                raise

            self._finishNativeInstall(True, None, name, fileName, destinationPath, renamedForSafety)
        except Exception as e:
            log.error("eSpeak Voice Designer: unable to install variant in NVDA", exc_info=True)
            ui.message(_("Unable to install the variant in NVDA: {error}").format(error=e))

    def _finishNativeInstall(self, success, error, name, fileName, destinationPath, renamedForSafety=False):
        if not success:
            ui.message(error or _("Variant installation was cancelled or failed."))
            return
        try:
            # Installation is only a copy operation. Keep the saved personal
            # variant as the current Designer source/baseline; do not switch the
            # editor to the newly installed native copy, otherwise a clean
            # personal project would immediately become a native Modified source.
            _refreshNvdaVariantCache(self._synth)
            currentPersonalId = self._selectedVariantId
            self._refreshVariantChoices(currentPersonalId)
        except Exception:
            log.debugWarning("eSpeak Voice Designer: unable to refresh variants after native install", exc_info=True)
        # The source was already a clean saved personal variant. Keep it clean
        # and discard any stale continuation draft without changing its baseline.
        _deleteDraftState()
        self._refreshModifiedTitle()
        if renamedForSafety:
            ui.message(_("An NVDA eSpeak variant with that name already exists and was left unchanged. The new variant was installed as {name}.").format(name=name))
        else:
            ui.message(_("Variant {name} installed in the NVDA eSpeak variants folder.").format(name=name))

    def _exportEditorState(self):
        # Capture the controls exactly as they are now, while preserving the
        # baseline used by Ctrl+Delete. OK stores this state persistently as a
        # draft so it can be resumed after restarting NVDA or Windows.
        self._values = self._readControls()
        sectionIndex = self.sectionChoice.GetSelection()
        if sectionIndex < 0:
            sectionIndex = 0
        return {
            "baseVoice": self._baseVoice,
            "baselineVoice": self._baselineVoice,
            "selectedVariantId": self._selectedVariantId,
            "selectedVariantFileName": self._selectedVariantFileName,
            "selectedVariantDisplayName": self._selectedVariantDisplayName,
            "values": copy.deepcopy(self._values),
            "baselineValues": copy.deepcopy(self._baselineValues),
            "baselinePresent": set(self._baselinePresent),
            "isNewVariant": bool(self._isNewVariant),
            "showSourceWhenClean": bool(self._showSourceWhenClean),
            "sourceVariantPath": self._sourceVariantPath,
            "sourceVariantText": self._sourceVariantText,
            "sourceUsesVariantReset": bool(self._sourceUsesVariantReset),
            "sourcePatchBaselineValues": copy.deepcopy(
                getattr(self, "_sourcePatchBaselineValues", self._baselineValues)
            ),
            "variantName": str(self.variantName.GetValue()),
            "previewText": str(self.previewText.GetValue()),
            "draftBaselineVariantName": str(getattr(self, "_draftBaselineVariantName", "new-variant")),
            "draftBaselinePreviewText": str(getattr(self, "_draftBaselinePreviewText", _DEFAULT_PREVIEW_TEXT)),
            "sectionIndex": int(sectionIndex),
            "consonantMacroState": copy.deepcopy(getattr(self, "_consonantMacroState", {})),
            "toneMacroState": copy.deepcopy(getattr(self, "_toneMacroState", {})),
            "klattDampingState": {
                "value": _numericValue(self.klattDamping, 0) if hasattr(self, "klattDamping") else 0,
                "anchorWidths": list(getattr(self, "_klattDampingAnchorWidths", [100, 100, 100, 100])),
            },
        }

    def _hasDraftContent(self):
        """Return True when any useful unsaved editor work differs from its base."""
        try:
            if self._voiceStateChanged(self._readControls()):
                return True
            if str(self.previewText.GetValue()) != str(getattr(self, "_draftBaselinePreviewText", _DEFAULT_PREVIEW_TEXT)):
                return True
            if str(self.variantName.GetValue()).strip() != str(getattr(self, "_draftBaselineVariantName", "new-variant")).strip():
                return True
            return False
        except Exception:
            return True

    def _onOk(self, evt):
        # Enter/OK keeps the editor work as a persistent draft, then always
        # restores NVDA to the synthesizer/voice that was active before opening
        # the Designer. A clean, already-saved state does not create a draft.
        self._exitFocusState = self._captureFocusState()
        self._editorState = self._exportEditorState()
        if self._isModifiedState():
            _writeDraftState(self._editorState)
        else:
            _deleteDraftState()
        self._committed = True
        self._restoreSessionState()
        self.EndModal(wx.ID_OK)

    def _restoreSessionState(self):
        # Both OK and Cancel/Esc leave NVDA exactly on the synthesizer it was
        # using before the Designer opened. The editor runtime voice is private
        # and must never leak into normal NVDA use after the window closes.
        if getattr(self, "_sessionRestored", False):
            return
        self._sessionRestored = True
        _discardRuntimeVoiceFile()
        if self._autoSwitchedSynth and self._previousSynthName:
            try:
                if not synthDriverHandler.setSynth(self._previousSynthName):
                    log.error(
                        "eSpeak Voice Designer: unable to restore previous synthesizer %s",
                        self._previousSynthName,
                    )
                    _restoreOriginalVoice(self._originalVoice, self._originalVariant)
            except Exception:
                log.error(
                    "eSpeak Voice Designer: error restoring previous synthesizer %s",
                    self._previousSynthName,
                    exc_info=True,
                )
                _restoreOriginalVoice(self._originalVoice, self._originalVariant)
            return
        _restoreOriginalVoice(self._originalVoice, self._originalVariant)

    def _restoreAndClose(self):
        self._restoreSessionState()
        self.EndModal(wx.ID_CANCEL)

    def _onCancel(self, evt):
        self._exitFocusState = self._captureFocusState()
        self._restoreAndClose()

    def _onClose(self, evt):
        self._exitFocusState = self._captureFocusState()
        self._restoreSessionState()
        evt.Skip()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        self._dialog = None
        self._dialogOpening = False
        self._workingState = None
        self._workingSynthObject = None
        self._lastFocusState = None
        self._menuItem = None
        if getattr(globalVars.appArgs, "secure", False):
            return
        try:
            os.makedirs(_variantDirectory(), exist_ok=True)
            _removeLegacyStockVariantCache()
        except Exception:
            log.debugWarning("eSpeak Voice Designer: unable to create variant directory", exc_info=True)
        try:
            menu = gui.mainFrame.sysTrayIcon.preferencesMenu
            self._menuItem = menu.Append(wx.ID_ANY, ADDON_TITLE + "...")
            gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self._onMenu, self._menuItem)
        except Exception:
            log.debugWarning("eSpeak Voice Designer: unable to add Preferences menu item", exc_info=True)

    def _focusExistingDialog(self):
        dlg = self._dialog
        if dlg is None:
            return False
        try:
            if dlg.IsBeingDeleted():
                self._dialog = None
                return False
            dlg.Raise()
            dlg.SetFocus()
            return True
        except Exception:
            self._dialog = None
            return False

    def _showDialog(self):
        if self._focusExistingDialog() or self._dialogOpening:
            return
        self._dialogOpening = True
        popupPrepared = False
        dlg = None
        previousSynthName = None
        autoSwitchedSynth = False
        try:
            currentSynth = synthDriverHandler.getSynth()
            previousSynthName = getattr(currentSynth, "name", None) if currentSynth is not None else None
            if previousSynthName != "espeak":
                if not synthDriverHandler.setSynth("espeak"):
                    raise RuntimeError(_("Unable to activate eSpeak NG automatically."))
                currentSynth = synthDriverHandler.getSynth()
                if currentSynth is None or getattr(currentSynth, "name", "") != "espeak":
                    raise RuntimeError(_("eSpeak NG is not available in this NVDA installation."))
                autoSwitchedSynth = bool(previousSynthName)

            gui.mainFrame.prePopup()
            popupPrepared = True
            # The working draft is persistent and deliberately independent of
            # the current synth object. This is what lets unfinished work survive
            # NVDA and Windows restarts while NVDA itself returns to the user's
            # normal synthesizer whenever the Designer closes.
            usableWorkingState = _readDraftState()
            dlg = VoiceDesignerDialog(
                gui.mainFrame,
                previousSynthName=previousSynthName,
                autoSwitchedSynth=autoSwitchedSynth,
                workingState=usableWorkingState,
                initialFocusState=copy.deepcopy(self._lastFocusState),
            )
            self._dialog = dlg
            self._dialogOpening = False
            result = dlg.ShowModal()
            self._lastFocusState = copy.deepcopy(getattr(dlg, "_exitFocusState", None))
            # Draft persistence is handled by the dialog itself. Esc never
            # overwrites an existing draft; OK writes the current one. Variant
            # changes and Ctrl+S can explicitly remove it. Keep only legacy
            # in-memory fields empty so disk remains the single source of truth.
            self._workingState = None
            self._workingSynthObject = None
        except Exception as e:
            # If we switched synth only to open the designer and construction
            # failed before the dialog became usable, put NVDA back exactly on
            # the synthesizer it was using before the shortcut.
            if autoSwitchedSynth and previousSynthName and dlg is None:
                try:
                    synthDriverHandler.setSynth(previousSynthName)
                except Exception:
                    log.error(
                        "eSpeak Voice Designer: unable to restore previous synth after open failure",
                        exc_info=True,
                    )
            log.error("eSpeak Voice Designer: unable to open dialog", exc_info=True)
            gui.messageBox(
                _("Unable to open {name}.\n\n{errorType}: {error}").format(name=ADDON_TITLE, errorType=type(e).__name__, error=e),
                ADDON_TITLE,
                wx.OK | wx.ICON_ERROR,
            )
        finally:
            self._dialogOpening = False
            if dlg is not None:
                if self._dialog is dlg:
                    self._dialog = None
                try:
                    dlg.Destroy()
                except Exception:
                    pass
            if popupPrepared:
                gui.mainFrame.postPopup()

    def _onMenu(self, evt):
        wx.CallAfter(self._showDialog)

    @scriptHandler.script(
        description=_("Open eSpeak Voice Designer."),
        gesture="kb:NVDA+alt+v",
        category=ADDON_TITLE,
    )
    def script_openEspeakVoiceDesigner(self, gesture):
        wx.CallAfter(self._showDialog)

    def terminate(self):
        try:
            if self._menuItem is not None:
                try:
                    gui.mainFrame.sysTrayIcon.preferencesMenu.Remove(self._menuItem)
                except Exception:
                    pass
                self._menuItem = None
            self._workingSynthObject = None
            _discardRuntimeVoiceFile()
        finally:
            super().terminate()
