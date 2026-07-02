from dataclasses import dataclass
import re


VIRTUAL_DEVICE_KEYWORDS = (
    "blackhole",
    "soundflower",
    "loopback",
    "background music",
    "vb-cable",
    "vb cable",
    "vb-audio",
    "vb audio",
    "cable input",
    "cable output",
    "voicemeeter",
    "audio hijack",
    "rogue amoeba",
    "virtual",
)


@dataclass(frozen=True)
class InputDeviceChoice:
    name: str
    raw: object
    is_loopback: bool
    is_virtual: bool

    @property
    def display_name(self):
        tag = "Loopback" if self.is_loopback else "Mic"
        if self.is_virtual:
            tag += ", virtual"
        return f"{self.name} [{tag}]"


@dataclass(frozen=True)
class OutputDeviceChoice:
    name: str
    index: int
    is_virtual: bool
    max_output_channels: int = 0
    default_samplerate: int = 48000

    @property
    def display_name(self):
        return f"{self.name} (virtual)" if self.is_virtual else self.name


def normalize_device_name(name):
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def is_virtual_device_name(name):
    normalized = normalize_device_name(name)
    return any(keyword in normalized for keyword in VIRTUAL_DEVICE_KEYWORDS)


def is_vb_cable_playback_name(name):
    normalized = normalize_device_name(name)
    return "cable input" in normalized or "vb-audio" in normalized or "vb audio" in normalized


def conference_mic_hint(output_name):
    if not output_name:
        return (
            "No virtual playback device found. Install VB-Audio Virtual Cable, then "
            "select CABLE Input here and CABLE Output as the microphone in Slack/Zoom."
        )
    if is_vb_cable_playback_name(output_name):
        return (
            'In Slack/Zoom, set the microphone to "CABLE Output '
            '(VB-Audio Virtual Cable)". Use headphones.'
        )
    if is_virtual_device_name(output_name):
        return f'In Slack/Zoom, set the microphone to "{output_name}". Use headphones.'
    return (
        "This output is not virtual, so others will not hear it as your mic. "
        "Install VB-Audio Virtual Cable and pick CABLE Input here."
    )


def should_apply_mic_noise_gate(input_device):
    if input_device is None:
        return False
    name = getattr(input_device, "name", "")
    return not bool(getattr(input_device, "isloopback", False)) and not is_virtual_device_name(name)


def same_physical_device(input_name, output_name):
    return bool(input_name and output_name) and normalize_device_name(input_name) == normalize_device_name(output_name)


def refresh_portaudio_devices():
    try:
        import sounddevice as sd

        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def query_input_devices(include_loopback=True):
    try:
        import soundcard as sc

        devices = sc.all_microphones(include_loopback=include_loopback)
    except Exception:
        return []
    return [
        InputDeviceChoice(
            name=getattr(device, "name", ""),
            raw=device,
            is_loopback=bool(getattr(device, "isloopback", False)),
            is_virtual=is_virtual_device_name(getattr(device, "name", "")),
        )
        for device in devices
    ]


def query_output_devices():
    refresh_portaudio_devices()
    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception:
        return []

    result = []
    for index, info in enumerate(devices):
        try:
            max_channels = int(info.get("max_output_channels", 0))
        except AttributeError:
            max_channels = int(info["max_output_channels"])
        if max_channels <= 0:
            continue
        try:
            name = str(info.get("name", ""))
            sample_rate = int(float(info.get("default_samplerate", 48000)))
        except AttributeError:
            name = str(info["name"])
            sample_rate = int(float(info["default_samplerate"]))
        result.append(
            OutputDeviceChoice(
                name=name,
                index=index,
                is_virtual=is_virtual_device_name(name),
                max_output_channels=max_channels,
                default_samplerate=sample_rate,
            )
        )
    return result


def resolve_input_device_by_name(name, include_loopback=True):
    devices = query_input_devices(include_loopback=include_loopback)
    normalized = normalize_device_name(name)
    for choice in devices:
        if normalize_device_name(choice.name) == normalized:
            return choice.raw
    return None


def resolve_output_device_index(name):
    if not name:
        return None
    normalized = normalize_device_name(name)
    for choice in query_output_devices():
        if normalize_device_name(choice.name) == normalized:
            return choice.index
    return None


def first_real_microphone(input_choices):
    for choice in input_choices:
        if not choice.is_loopback and not choice.is_virtual:
            return choice
    return input_choices[0] if input_choices else None


def first_virtual_output(output_choices):
    for choice in output_choices:
        if choice.is_virtual:
            return choice
    return output_choices[0] if output_choices else None
