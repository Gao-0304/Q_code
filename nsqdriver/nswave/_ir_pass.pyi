from ._checkers import BaseChecker as BaseChecker
from ._optimizations import BaseOptimizer as BaseOptimizer
from ._rules import BaseRule as BaseRule
from ._translate import NormalTranslator as NormalTranslator
from .kernel import Kernel as Kernel

def ir_pass(kernel: Kernel): ...
