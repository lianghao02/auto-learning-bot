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


    def test_e_and_f_options_parsing(self):
        """測試包含 E、F 等多選項題型（如英業達實務案例題 8, 9, 10 為 E）可 100% 完整解析。"""
        questions_10 = [
            {"index": i, "type": "單選", "q_text": f"第 {i} 題", "options": [{"label": l, "text": f"選項 {l}"} for l in ("A", "B", "C", "D", "E")]}
            for i in range(1, 11)
        ]
        raw_text = """
1. C
2. C
3. C
4. B
5. D
6. C
7. A
8. E
9. E
10. E
"""
        result = parse_ai_quiz_answers(raw_text, questions_10)
        self.assertEqual(len(result), 10)
        self.assertEqual(result[1], ["C"])
        self.assertEqual(result[7], ["A"])
        self.assertEqual(result[8], ["E"])
        self.assertEqual(result[9], ["E"])
        self.assertEqual(result[10], ["E"])

    def test_parse_multiple_choice_answers(self):
        """測試多選答案解析：支援逗號、頓號、空白、連寫字母、數字等格式"""
        from utils.helpers import parse_multiple_choice_answers

        # 逗號與空格
        self.assertEqual(parse_multiple_choice_answers("A,B,C,D"), ["A", "B", "C", "D"])
        self.assertEqual(parse_multiple_choice_answers("A, B, C"), ["A", "B", "C"])
        self.assertEqual(parse_multiple_choice_answers("b, c"), ["B", "C"])

        # 頓號
        self.assertEqual(parse_multiple_choice_answers("A、B、D"), ["A", "B", "D"])

        # 全形逗號、空白、斜線、分號
        self.assertEqual(parse_multiple_choice_answers("A，C，D"), ["A", "C", "D"])
        self.assertEqual(parse_multiple_choice_answers("A B C D"), ["A", "B", "C", "D"])
        self.assertEqual(parse_multiple_choice_answers("A/B/C"), ["A", "B", "C"])
        self.assertEqual(parse_multiple_choice_answers("A;C"), ["A", "C"])

        # 連寫字母 (ABCD, ACD, BC)
        self.assertEqual(parse_multiple_choice_answers("ABCD"), ["A", "B", "C", "D"])
        self.assertEqual(parse_multiple_choice_answers("ACD"), ["A", "C", "D"])
        self.assertEqual(parse_multiple_choice_answers("BC"), ["B", "C"])

        # 數字格式 (1,2,3,4 或 1 2 4)
        self.assertEqual(parse_multiple_choice_answers("1,2,3,4"), ["A", "B", "C", "D"])
        self.assertEqual(parse_multiple_choice_answers("1 3 4"), ["A", "C", "D"])
        self.assertEqual(parse_multiple_choice_answers("2,3"), ["B", "C"])

        # 清單輸入
        self.assertEqual(parse_multiple_choice_answers(["A", "C", "D"]), ["A", "C", "D"])
        self.assertEqual(parse_multiple_choice_answers(["A,B", "D"]), ["A", "B", "D"])

        # 空值與邊界情況
        self.assertEqual(parse_multiple_choice_answers(""), [])
        self.assertEqual(parse_multiple_choice_answers(None), [])

    def test_checkbox_group_answering_and_verification(self):
        """測試在 Checkbox DOM 群組上，依預期答案集合精確勾選，並重新讀取 checked 集合比對"""
        from utils.helpers import parse_multiple_choice_answers

        class FakeCheckbox:
            def __init__(self, value, is_checked=False):
                self.value = value
                self.checked = is_checked

            def get_attribute(self, attr):
                if attr == "value":
                    return self.value
                return ""

        # 模擬 4 個 checkbox，value 分別為 "0", "1", "2", "3" (0-based)
        checkboxes = [FakeCheckbox(str(i), False) for i in range(4)]
        ans_raw = "A,B,D"  # 預期勾選 0 (A), 1 (B), 3 (D)
        expected_letters = parse_multiple_choice_answers(ans_raw, num_options=len(checkboxes))
        expected_set = set(expected_letters)

        # 執行模擬勾選邏輯（與 app.py 相同）
        for i, cb in enumerate(checkboxes):
            let = chr(ord('A') + i)
            cb_val = cb.get_attribute("value").strip().lower()
            should_check = (let in expected_set)
            if not should_check:
                if cb_val and cb_val in [l.lower() for l in expected_set]:
                    should_check = True

            if should_check and not cb.checked:
                cb.checked = True
            elif not should_check and cb.checked:
                cb.checked = False

        actual_letters = [chr(ord('A') + i) for i, cb in enumerate(checkboxes) if cb.checked]
        actual_set = set(actual_letters)

        self.assertEqual(expected_set, {"A", "B", "D"})
        self.assertEqual(actual_set, expected_set)


if __name__ == "__main__":
    unittest.main()

