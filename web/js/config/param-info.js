/**
 * Parameter info descriptions for tooltip overlays
 */
window.PARAM_INFO = {
    cct: 'Color temperature in Kelvin. 2700K = warm/amber (tungsten), 4000K = neutral white, 5600K = daylight, 6500K = cool/overcast. Lower = warmer, higher = cooler.',
    duv: 'Distance from Planckian locus. Duv=0 = perfect black-body color. Positive = greenish tint, negative = pinkish. |Duv| < 0.003 = imperceptible, > 0.006 = visible tint.',
    lux: 'Illuminance at sensor. 1 lux = full moon, 300\u2013500 lux = office, 1000+ lux = bright stage wash.',
    uv: "CIE 1976 u'v' chromaticity. More perceptually uniform than xy. Used for color difference calculations between sources.",
    r9: 'CRI for saturated red. Critical for skin tones and warm costumes. R9 < 0 = reds look dull/brown. R9 > 50 = good. R9 > 90 = excellent.',
    cs: 'Circadian Stimulus (0\u20130.7). Measures melatonin suppression. CS > 0.3 = alerting, CS < 0.1 = sleep-friendly. Key for healthcare and architectural lighting.',
    eml: 'Equivalent Melanopic Lux. Warm 2700K @ 300lux \u2248 100 EML. Cool 6500K @ 300lux \u2248 250 EML. Used in WELL Building Standard for occupant health.',
    cri: 'Average CRI (R1\u2013R8). Ra > 90 = excellent, 80\u201390 = good, < 80 = poor. Stage/TV minimum: 90+. Does not include saturated colors (R9\u2013R14).',
    cie: 'CIE 1931 xy chromaticity coordinates. Defines the exact color point of the light source. Used universally in lighting specifications.',
    flicker_freq: 'Dominant flicker frequency. 100Hz (50Hz mains) or 120Hz (60Hz). Higher = less perceptible. Below 80Hz = visible to most people.',
    flicker_mod: 'Percent modulation. How much light output varies. < 8% @ 100Hz = safe (IEEE 1789). > 30% = may cause headaches and eye strain.',
    flicker_fi: 'Flicker Index (0\u20131). Area-based metric. FI < 0.1 = low, 0.1\u20130.3 = moderate, > 0.3 = high. More comprehensive than modulation alone.',
    r13: 'CRI for light skin tones (pale Caucasian complexion). Critical for stage, film, and broadcast where performers must look natural. R13 > 90 = excellent.',
    r14: 'CRI for green foliage. Important for scenic greenery and natural outdoor reproductions. R14 > 90 = excellent, < 80 = foliage looks dull or unnatural.',
};
