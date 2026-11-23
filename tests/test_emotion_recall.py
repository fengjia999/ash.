import unittest

from emotion_recall import detect_emotion, evidence_emotion, emotion_adjustment


class EmotionHintTests(unittest.TestCase):
    def test_explicit_feelings_and_abstentions(self):
        for text, label in [('我今天很难过', 'sadness'), ('我现在有点焦虑', 'anxiety'),
                            ('我很开心', 'joy'), ('我现在觉得被理解了', 'supported')]:
            with self.subTest(text=text):
                self.assertEqual(label, detect_emotion(text, current=True)['label'])
        for text in ['我不难过', '我很难过但也很开心', '你今天很难过吗',
                     '我觉得他很难过', '我的朋友很难过', '“我很难过”这句话怎么翻译',
                     '我上次很难过时你说了什么', '钢琴练习安排', '如果我很难过呢']:
            with self.subTest(text=text):
                self.assertIsNone(detect_emotion(text, current=True))

    def test_user_evidence_only_and_mixed_states_abstain(self):
        self.assertIsNone(evidence_emotion([{'role': 'assistant', 'quote': '我很开心'}]))
        self.assertIsNone(evidence_emotion([
            {'role': 'user', 'quote': '我很难过'},
            {'role': 'user', 'quote': '我现在很开心'},
        ]))
        self.assertEqual('sadness', evidence_emotion([
            {'role': 'user', 'quote': '我很难过'},
            {'role': 'assistant', 'quote': '我很开心'},
        ])['label'])

    def test_support_is_compatible_without_same_mood(self):
        sad = detect_emotion('我很难过')
        supported = detect_emotion('我现在很安心')
        happy = detect_emotion('我很开心')
        self.assertGreater(emotion_adjustment(sad, supported, .04), 0)
        self.assertLess(emotion_adjustment(sad, happy, .04), 0)
        self.assertEqual(0, emotion_adjustment(None, happy, .04))
