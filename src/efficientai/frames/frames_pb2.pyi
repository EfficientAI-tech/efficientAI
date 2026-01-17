from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class TextFrame(_message.Message):
    __slots__ = ("id", "name", "text")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    id: int
    name: str
    text: str
    def __init__(self, id: _Optional[int] = ..., name: _Optional[str] = ..., text: _Optional[str] = ...) -> None: ...

class AudioRawFrame(_message.Message):
    __slots__ = ("id", "name", "audio", "sample_rate", "num_channels", "pts")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    AUDIO_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_RATE_FIELD_NUMBER: _ClassVar[int]
    NUM_CHANNELS_FIELD_NUMBER: _ClassVar[int]
    PTS_FIELD_NUMBER: _ClassVar[int]
    id: int
    name: str
    audio: bytes
    sample_rate: int
    num_channels: int
    pts: int
    def __init__(self, id: _Optional[int] = ..., name: _Optional[str] = ..., audio: _Optional[bytes] = ..., sample_rate: _Optional[int] = ..., num_channels: _Optional[int] = ..., pts: _Optional[int] = ...) -> None: ...

class TranscriptionFrame(_message.Message):
    __slots__ = ("id", "name", "text", "user_id", "timestamp")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    id: int
    name: str
    text: str
    user_id: str
    timestamp: str
    def __init__(self, id: _Optional[int] = ..., name: _Optional[str] = ..., text: _Optional[str] = ..., user_id: _Optional[str] = ..., timestamp: _Optional[str] = ...) -> None: ...

class MessageFrame(_message.Message):
    __slots__ = ("data",)
    DATA_FIELD_NUMBER: _ClassVar[int]
    data: str
    def __init__(self, data: _Optional[str] = ...) -> None: ...

class Frame(_message.Message):
    __slots__ = ("text", "audio", "transcription", "message")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    AUDIO_FIELD_NUMBER: _ClassVar[int]
    TRANSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    text: TextFrame
    audio: AudioRawFrame
    transcription: TranscriptionFrame
    message: MessageFrame
    def __init__(self, text: _Optional[_Union[TextFrame, _Mapping]] = ..., audio: _Optional[_Union[AudioRawFrame, _Mapping]] = ..., transcription: _Optional[_Union[TranscriptionFrame, _Mapping]] = ..., message: _Optional[_Union[MessageFrame, _Mapping]] = ...) -> None: ...
