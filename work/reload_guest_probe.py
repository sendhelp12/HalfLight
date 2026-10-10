"""Rebind the leased source modules in the same running Half Sword session."""
import time
from setup import ROOT


def reload():
    runtime=ROOT/'outputs/HalfLightNext/runtime'
    path=runtime/'actor-capture.ini';temporary=path.with_suffix('.tmp')
    temporary.write_text('Enabled=1\nEpoch='+str(time.time_ns())+'\n',encoding='ascii')
    temporary.replace(path)


if __name__=='__main__':reload()
