import numpy as np
from _typeshed import Incomplete

__all__ = ['AssemblyError', 'GenTagMixin', 'NSQCommand', 'QInsFrame', 'nsw_config', 'QInsEnvelope', 'QInsWait', 'QInsNop', 'QInsJumpImmediate', 'QInsPlayImm', 'QInsWaitTrig', 'QInsFrameRst', 'QInsWaitTrig', 'QInsFrameAdd', 'QInsCapture']

def nsw_config(name, value) -> None: ...

class QNumber:
    value: int
    def __init__(self) -> None: ...
    def __int__(self) -> int: ...
    def __float__(self) -> float: ...
    def __bool__(self) -> bool: ...

class AssemblyError(RuntimeError): ...

class GenTagMixin:
    @property
    def generate_tag(self): ...

class NSQCommand(GenTagMixin):
    tag: Incomplete
    def __init__(self) -> None: ...
    @property
    def overhead(self): ...
    @classmethod
    def compile(cls, inst_list: list[Self]) -> tuple[np.ndarray, str]: ...

class QInsFrame(NSQCommand):
    freq: Incomplete
    phase: Incomplete
    idx: Incomplete
    line: Incomplete
    def __init__(self, freq, phase, idx, line) -> None: ...
    @property
    def overhead(self): ...

class QInsEnvelope(NSQCommand):
    envelope: Incomplete
    envelop_slice: Incomplete
    def __init__(self, envelope: np.ndarray) -> None: ...
    def __len__(self) -> int: ...
    def __bytes__(self) -> bytes: ...

class QInsFrameRst(NSQCommand):
    @property
    def overhead(self): ...

class QInsFrameAdd(NSQCommand):
    frames: Incomplete
    frequency: Incomplete
    phase: Incomplete
    def __init__(self, frames: list[QInsFrame], frequency: float, phase: float) -> None: ...
    @property
    def overhead(self): ...

class QInsWait(NSQCommand):
    width: Incomplete
    def __init__(self, width) -> None: ...
    @property
    def overhead(self): ...

class QInsWaitTrig(NSQCommand):
    def __init__(self) -> None: ...
    @property
    def overhead(self): ...

class QInsNop(NSQCommand):
    @property
    def overhead(self): ...

class QInsJumpImmediate(NSQCommand):
    idx: Incomplete
    def __init__(self, idx: int) -> None: ...
    @property
    def overhead(self): ...

class QInsCapture(NSQCommand):
    fre: Incomplete
    acq_width: Incomplete
    delay_width: Incomplete
    play_width: Incomplete
    para: Incomplete
    def __init__(self, fre: list[int], acq_width: float, delay_width: float, play_width: float, raw_data_store: bool, iq_data_store: bool, judge_data_store: bool, double_fre_mode: bool) -> None: ...
    @property
    def overhead(self): ...

class QInsPlayImm(NSQCommand):
    frame: Incomplete
    freq: Incomplete
    amp: Incomplete
    bias: Incomplete
    envelope: Incomplete
    phase: Incomplete
    def __init__(self, frame: QInsFrame, envelope: QInsEnvelope, amp, bias, freq, phase) -> None: ...
    @property
    def overhead(self): ...
