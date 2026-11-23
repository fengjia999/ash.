"""Conservative, local emotion hints; never rewrite evidence or embedding text."""
import re

VERSION = 1
# This first experiment deliberately recognizes explicit Chinese expressions only.
CUES = {
    'sadness': ('难过', '伤心', '低落', '委屈', '孤独'),
    'anxiety': ('焦虑', '紧张', '害怕', '不安'),
    'anger': ('生气', '愤怒', '恼火'),
    'joy': ('开心', '高兴', '兴奋', '幸福'),
    'calm': ('平静', '放松'),
    'supported': ('安心', '踏实', '被理解', '被接住', '被支持', '好多了'),
}
NEGATIVE = {'sadness', 'anxiety', 'anger'}
HISTORICAL = re.compile(r'还记得|记不记得|回忆|那次|当时|上次|以前|曾经|过去|昨天|前天')


def detect_emotion(text, *, current=False):
    """Abstain on ambiguous/quoted/third-person emotion or explicit past recall."""
    text = str(text or '').strip()
    if not text or len(text) > 1000:
        return None
    if current and HISTORICAL.search(text):
        return None
    if re.search(r'[“”「」『』\"]|他说|她说|你说|朋友|角色|假如|如果|比如', text):
        return None
    matches = []
    for label, cues in CUES.items():
        for cue in cues:
            for match in re.finditer(re.escape(cue), text):
                prefix = text[max(0, match.start() - 12):match.start()]
                # Require a first-person or explicit present-state expression.
                if not re.search(r'(?:我(?:现在|今天)?|现在|今天|真的|好|很|有点|感到|觉得)[^，。！？；\n]{0,8}$', prefix):
                    continue
                if re.search(r'不|没|别|并非|不是|不再|不会', prefix[-6:]):
                    continue
                if re.search(r'他|她|你', prefix):
                    continue
                matches.append((label, cue))
    labels = {label for label, _ in matches}
    if len(labels) != 1:
        return None
    return {'version': VERSION, 'label': matches[0][0], 'confidence': 0.85,
            'cue': matches[0][1], 'method': 'explicit_words'}


def evidence_emotion(anchors):
    """Use user evidence only; mixed states abstain rather than erase a turn."""
    if not isinstance(anchors, list):
        return None
    hints = [detect_emotion(a.get('quote')) for a in anchors
             if isinstance(a, dict) and a.get('role') == 'user']
    hints = [hint for hint in hints if hint]
    if not hints or len({hint['label'] for hint in hints}) != 1:
        return None
    return hints[-1]


def emotion_adjustment(query_hint, memory_hint, weight):
    """Bounded compatibility bonus/penalty, independent of semantic eligibility."""
    if not query_hint or not memory_hint:
        return 0.0
    current, past = query_hint['label'], memory_hint['label']
    if current == past:
        compatibility = 1.0
    elif current in NEGATIVE and past == 'supported':
        compatibility = 0.6
    elif (current in NEGATIVE and past == 'joy') or (current == 'joy' and past in NEGATIVE):
        compatibility = -1.0
    else:
        compatibility = 0.0
    return weight * compatibility * query_hint['confidence'] * memory_hint['confidence']
