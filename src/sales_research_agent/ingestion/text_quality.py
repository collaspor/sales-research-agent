"""正文可读性检查；识别明确损坏，不按语言屏蔽正常文本。"""

import re


def is_readable(text: str) -> bool:
    """拒绝替换字符、控制字符及本次故障特有的混杂西里尔乱码。"""
    if "\ufffd" in text or any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        return False
    # GBK 被误解码成西里尔字符时，非俄语字母与大小写连续混杂。
    unusual = len(re.findall(r"[Ѐ-Џѐ-џ]", text))
    cyrillic = len(re.findall(r"[\u0400-\u04ff]", text))
    uppercase = len(re.findall(r"[Ѐ-Я]", text))
    return not (unusual >= 3 and cyrillic >= 10 and unusual / cyrillic > 0.08
                and 0.35 < uppercase / cyrillic < 0.95)
