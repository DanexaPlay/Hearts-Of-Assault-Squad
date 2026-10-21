"""Organisation deployment scaling without inventing strategic casualties."""
import math
from .core import BridgeError


def organization_ratio(b,division):
    record=b.get('organization_snapshot',{}).get(division.get('id'))
    if record is None:
        # Old, synthetic formation fixtures have no live organisation cache.
        if b.get('organization_scaling_required'):
            raise BridgeError('Missing verified maximum organisation for '+str(division.get('id')))
        return 1.0
    current=record.get('current');maximum=record.get('maximum')
    if (isinstance(current,bool) or isinstance(maximum,bool) or
        not isinstance(current,(int,float)) or not isinstance(maximum,(int,float)) or
        not math.isfinite(current) or not math.isfinite(maximum) or current<0 or maximum<=0):
        raise BridgeError('Invalid division organisation snapshot')
    if abs(current-division['organization_points'])>0.00002:
        raise BridgeError('Organisation snapshot differs from saved division')
    return min(1.0,current/maximum)


def deployed_count(base,ratio):
    # Preserve each equipped battalion/support component and complete crews.
    return max(1,math.ceil(base*ratio)) if base>0 else 0
