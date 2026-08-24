"""人機協同與 AI 作答答案解析單元測試。"""

import unittest
from utils.helpers import parse_ai_quiz_answers


class QuizAnswerParsingTests(unittest.TestCase):
    def setUp(self):
        self.sample_questions = [
            {
                "index": 1,
                "type": "是非",
                "q_text": "資訊安全人人都需要遵守。",
                "options": [{"label": "A", "text": "是"}, {"label": "B", "text": "否"}],
            },
            {
                "index": 2,
                "type": "單選",
                "q_text": "臺灣最高的山是？",
                "options": [
                    {"label": "A", "text": "阿里山"},
                    {"label": "B", "text": "玉山"},
                    {"label": "C", "text": "陽明山"},
                    {"label": "D", "text": "雪山"},
                ],
            },
            {
                "index": 3,
                "type": "多選",
                "q_text": "以下屬於再生能源的有？",
                "options": [
                    {"label": "A", "text": "太陽能"},
                    {"label": "B", "text": "風力"},
                    {"label": "C", "text": "燃煤"},
                    {"label": "D", "text": "水力"},
                ],
            },
            {
                "index": 4,
                "type": "是非",
                "q_text": "地球是平的。",
                "options": [{"label": "A", "text": "是"}, {"label": "B", "text": "否"}],
            },
        ]

    def test_tf_negation_priority(self):
        """測試是非題否定詞（不正確、不是、錯誤）不會被肯定詞（正確、是）誤判。"""
        raw_text_1 = "1. 不正確\n2. B\n3. A、B、D\n4. 不是"
        result_1 = parse_ai_quiz_answers(raw_text_1, self.sample_questions)
        self.assertEqual(result_1[1], ["B"])
        self.assertEqual(result_1[2], ["B"])
        self.assertEqual(result_1[3], ["A", "B", "D"])
        self.assertEqual(result_1[4], ["B"])

        raw_text_2 = "1. 正確\n2. B\n3. A、B、D\n4. 是"
        result_2 = parse_ai_quiz_answers(raw_text_2, self.sample_questions)
        self.assertEqual(result_2[1], ["A"])
        self.assertEqual(result_2[4], ["A"])

    def test_line_by_line_pure_answers_fallback(self):
        """測試無題號純行格式（如 A\nD\nC\nB）可正確依行序自動映射。"""
        raw_text = "A\nB\nA, B, D\nB"
        result = parse_ai_quiz_answers(raw_text, self.sample_questions)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[1], ["A"])
        self.assertEqual(result[2], ["B"])
        self.assertEqual(result[3], ["A", "B", "D"])
        self.assertEqual(result[4], ["B"])

    def test_markdown_and_table_formats(self):
        """測試 Markdown 粗體、清單符號與表格列格式。"""
        raw_text = """
| 題號 | 建議答案 |
| 1 | **是** |
| 2 | - B |
| 3 | A、B、D |
| 4 | 錯誤 |
"""
        result = parse_ai_quiz_answers(raw_text, self.sample_questions)
        self.assertEqual(result[1], ["A"])
        self.assertEqual(result[2], ["B"])
        self.assertEqual(result[3], ["A", "B", "D"])
        self.assertEqual(result[4], ["B"])


if __name__ == "__main__":
    unittest.main()
