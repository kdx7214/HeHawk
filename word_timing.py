"""Reconstruct token-addressed words without timing trailing punctuation."""
def word_groups(tokens, times, durations, a, b):
    if not len(tokens) == len(times) == len(durations):
        raise ValueError('Mismatched token timing arrays')
    words = []
    lexical = False
    for i in range(a, b):
        t = tokens[i]
        start = times[i]
        end = start + durations[i]
        spoken = any(ch.isalnum() for ch in t)
        if not words or t.startswith(' '):
            words.append([t.strip(), i, i+1, start, end])
            lexical = spoken
        else:
            w = words[-1]
            w[0] += t
            w[2] = i+1
            if spoken:
                if not lexical:
                    w[3], w[4] = start, end
                else:
                    w[4] = max(w[4], end)
                lexical = True
    return words
