import time
from prometheus_client import Counter, Histogram

INVOCATIONS = Counter("gateway_invocations_total","Tool invocations",["tool","status"])
LATENCY = Histogram("gateway_invocation_seconds","Invocation latency",["tool"])

class Timer:
    def __init__(self): self.start = time.perf_counter()
    @property
    def ms(self): return (time.perf_counter()-self.start)*1000
