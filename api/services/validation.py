import re

LETTER_VALUES = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ',
    [10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 34, 35, 36, 37, 38]))


def check_digit(prefix: str) -> int:
    return sum((LETTER_VALUES[ch] if ch in LETTER_VALUES else int(ch)) * 2 ** i
               for i, ch in enumerate(prefix)) % 11 % 10


def validate_number(value: str) -> dict:
    number = value.strip().upper()
    reason = None
    if not re.fullmatch(r'[A-Z]{3}[UJZ][0-9]{7}', number):
        reason = 'Use three owner letters, U/J/Z, six serial digits and one check digit.'
    elif check_digit(number[:10]) != int(number[-1]):
        reason = f'Check digit mismatch: expected {check_digit(number[:10])}.'
    return {'number': number, 'valid': reason is None, 'reason': reason}
