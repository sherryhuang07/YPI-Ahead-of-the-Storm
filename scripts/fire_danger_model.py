"""Connecticut forest fire danger: 1964 National Fire Danger Rating System indexes.

`danger()` is a line-by-line translation of subroutine DANGER from W. A. Main (1969),
"Computer calculation of fire danger", USDA Forest Service Research Note NC-79
(https://research.fs.usda.gov/treesearch/11136). One coefficient is corrected: the
printed listing has A(2) = -0.85900, but the paper's own formula table gives -0.0859,
and only that value makes fine fuel moisture continuous where the regimes meet
(4.5 F). The listing's A(3) = -0.059660 and A(4) = -0.077373 are kept (they join
smoothly at 12.5 F and 27.5 F).

Connecticut DEEP rates fire danger from a Spread Index and a Build Up Index:

    class       Spread Index   Build Up Index
    LOW          0-10           0-22
    MODERATE    11-15          23-44
    HIGH        16-29          45-59
    VERY HIGH   30-39          60-74
    EXTREME     >=40           >=75
"""
import math

LEVELS = ['LOW', 'MODERATE', 'HIGH', 'VERY HIGH', 'EXTREME']
SPREAD_BREAKS = [11, 16, 30, 40]     # lower bounds of MODERATE..EXTREME
BUILDUP_BREAKS = [23, 45, 60, 75]

A = [-0.185900, -0.0859, -0.059660, -0.077373]
B = [30.0, 19.2, 13.8, 22.5]
C = [4.5, 12.5, 27.5]
D = [16.0, 10.0, 7.0, 5.0, 4.0, 3.0]


def danger(dry, wet, isnow, precip, wind, buo, iherb):
    """Return dict(df, ffm, adfm, grass, timber, fload, bui) exactly as subroutine DANGER.

    dry, wet: dry- and wet-bulb temperature (F); isnow: snow on the ground (bool);
    precip: preceding 24-hour precipitation (inches); wind: mph at 20 ft;
    buo: yesterday's buildup index; iherb: 1 cured, 2 transition, 3 green.
    """
    ffm = 99.0; adfm = 99.0; df = 0.0; fload = 0.0
    if isnow:
        grass = 0.0; timber = 0.0
        if precip > 0.1:
            buo = -50.0 * math.log(1.0 - (1.0 - math.exp(-buo / 50.0)) * math.exp(-1.175 * (precip - 0.1)))
            if buo < 0: buo = 0.0
        return dict(df=df, ffm=ffm, adfm=adfm, grass=grass, timber=timber, fload=fload, bui=buo)
    dif = dry - wet
    i = next((k for k in range(3) if dif <= C[k]), 3)
    ffm = B[i] * math.exp(A[i] * dif)
    j = next((k for k in range(6) if ffm > D[k]), None)
    df = 7.0 if j is None else float(j)          # Fortran: DF = I-1 with I starting at 1
    if ffm < 1.0: ffm = 1.0
    ffm = ffm + (iherb - 1) * 5.0
    if precip > 0.1:
        buo = -50.0 * math.log(1.0 - (1.0 - math.exp(-buo / 50.0)) * math.exp(-1.175 * (precip - 0.1)))
        if buo < 0: buo = 0.0
    buo = buo + df
    adfm = 0.9 * ffm + 0.5 + 9.5 * math.exp(-buo / 50.0)
    grass = timber = None
    if adfm >= 30.0:
        if ffm >= 30.0:
            return dict(df=df, ffm=ffm, adfm=adfm, grass=1.0, timber=1.0, fload=fload, bui=buo)
        timber = 1.0
        if wind < 14.0:                           # label 21: grass only, then clamp
            grass = 0.01312 * (wind + 6.0) * (33.0 - ffm) ** 1.65 - 3.0
            if timber <= 1.0:
                timber = 1.0
                if grass < 1.0: grass = 1.0
        else:                                     # label 25
            grass = 0.00918 * (wind + 14.0) * (33.0 - ffm) ** 1.65 - 3.0
            if grass > 99.0: grass = 99.0
            if timber > 99.0: timber = 99.0
    elif wind < 14.0:                             # labels 20-23
        timber = 0.01312 * (wind + 6.0) * (33.0 - adfm) ** 1.65 - 3.0
        grass = 0.01312 * (wind + 6.0) * (33.0 - ffm) ** 1.65 - 3.0
        if timber <= 1.0:
            timber = 1.0
            if grass < 1.0: grass = 1.0
    else:                                         # labels 24-27
        timber = 0.00918 * (wind + 14.0) * (33.0 - adfm) ** 1.65 - 3.0
        grass = 0.00918 * (wind + 14.0) * (33.0 - ffm) ** 1.65 - 3.0
        if grass > 99.0: grass = 99.0
        if timber > 99.0: timber = 99.0
    if timber > 0 and buo > 0:
        f = 1.75 * math.log10(timber) + 0.32 * math.log10(buo) - 1.640
        fload = 0.0 if f <= 0 else 10.0 ** f
    return dict(df=df, ffm=ffm, adfm=adfm, grass=grass, timber=timber, fload=fload, bui=buo)


def wet_bulb_f(temp_f, dewpoint_f):
    """Wet-bulb temperature (F) from temperature and dew point; Stull (2011) approximation."""
    t = (temp_f - 32) / 1.8; td = (dewpoint_f - 32) / 1.8
    rh = 100 * math.exp(17.625 * td / (243.04 + td)) / math.exp(17.625 * t / (243.04 + t))
    rh = min(max(rh, 5.0), 99.0)
    tw = (t * math.atan(0.151977 * (rh + 8.313659) ** 0.5) + math.atan(t + rh) - math.atan(rh - 1.676331)
          + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh) - 4.686035)
    return min(tw * 1.8 + 32, temp_f)


def herb_stage(day):
    """1 cured, 2 transition, 3 green. DEEP: cured in early spring, transition in late spring and
    fall, full leaf-out in summer. Calendar dates are an assumption checked against DEEP ratings."""
    md = (day.month, day.day)
    if (6, 1) <= md <= (9, 30): return 3
    if (5, 1) <= md <= (5, 31) or (10, 1) <= md <= (11, 15): return 2
    return 1


def level_index(value, breaks):
    return sum(value >= b for b in breaks)


def rating(spread, bui, rule='max'):
    """DEEP class from the two indexes. `rule` is chosen by validation against DEEP's ratings."""
    s = level_index(spread, SPREAD_BREAKS); b = level_index(bui, BUILDUP_BREAKS)
    return {'max': max(s, b), 'spread': s, 'buildup': b, 'min': min(s, b)}[rule]
