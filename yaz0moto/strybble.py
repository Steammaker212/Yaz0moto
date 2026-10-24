import re


CHARMAP = [
    '\0', 'a', 'b', 'c', 'd', 'e', 'f', 'g',
    'h',  'i', 'j', 'k', 'l', 'm', 'n', 'o',
    'p',  'q', 'r', 's', 't', 'u', 'v', 'w',
    'x',  'y', 'z', '0', '1', '2', '3', '4',
    '5',  'A', 'B', 'C', 'D', 'E', 'F', 'G',
    'H',  'I', 'J', 'K', 'L', 'M', 'N', 'O',
    'P',  'Q', 'R', 'S', 'T', 'U', 'V', 'W',
    'X',  'Y', 'Z', '6', '7', '8', '9', '_'
]

CHARMAP_BY_CHAR = {c: i for i, c in enumerate(CHARMAP)}  # reverse lookup


class StrybbleEncodeError(ValueError):
    pass


def strybble_encode(text, num_chars=16):
    if re.search(r'[_/.][_/.]', text):
        raise StrybbleEncodeError('Sequential special characters (_, / and .) are not supported.')

    text = text.replace(':', '____').replace('.', '___').replace('/', '__')

    if len(text) > num_chars:
        raise StrybbleEncodeError(
            f'Input too long (max {num_chars} characters, current input length: {len(text)}).'
        )

    text = text.ljust(num_chars, '\0')

    encoded_bin = ''
    for ch in text:
        idx = CHARMAP_BY_CHAR.get(ch)
        if idx is None:
            raise StrybbleEncodeError(f'Unsupported character: {ch!r}')
        encoded_bin += format(idx, '06b')

    value = int(encoded_bin, 2)
    hex_len = num_chars * 6 // 4
    return format(value, '0{}x'.format(hex_len))


def strybble_decode(hex_str, num_chars=16):
    if not hex_str:
        return ''
    value = int(hex_str, 16)
    bit_count = num_chars * 6
    bin_str = format(value, '0{}b'.format(bit_count))

    result_chars = []
    for i in range(0, bit_count, 6):
        idx = int(bin_str[i:i + 6], 2)
        ch = CHARMAP[idx]
        if ch == '\0':
            break
        result_chars.append(ch)

    return ''.join(result_chars)
