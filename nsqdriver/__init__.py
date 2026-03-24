from .NS_MCI import Driver as MCIDriver
from .NS_QSYNC import Driver as QSYNCDriver
from .NS_CST import Driver as CSTDriver
# from .compiler.ns_wave import InsChannel
# from .compiler.py_wave_asm import nsw_config, AssemblyError

version_pack = (0, 0, 238)

__version__ = '.'.join(str(_) for _ in version_pack)
__all__ = ['MCIDriver', 'QSYNCDriver', 'CSTDriver', 'InsChannel']
