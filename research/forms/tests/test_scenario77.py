"""Task 025: steps of a form scenario — read, resolved, generated and judged; real 1C is tested separately."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import form_launcher77 as form
import scenario77

DESCRIPTION = {"controls": [
    {"id": 4152, "class": "BUTTON", "caption": "&Закрыть", "identifier": ""},
    {"id": 4153, "class": "BUTTON", "caption": "Записать", "identifier": "КнЗаписать"},
    {"id": 4154, "class": "1CEDIT", "caption": "Кем", "identifier": "Фамилия"},
    {"id": 4155, "class": "1CEDIT", "caption": "Кем", "identifier": "Имя"},
    {"id": 4156, "class": "CHECKBOX", "caption": "Флажок", "identifier": "Флажок77"},
    {"id": 4157, "class": "STATIC", "caption": "Итог:", "identifier": ""},
]}
RUN = "run-1"


def trip(**changes):
    return dict({"returned": True, "complete": True, "messages": [], "diagnostics": []}, **changes)


class StepsTests(unittest.TestCase):
    def test_steps_are_numbered_and_normalized(self):
        steps = scenario77.steps({"steps": [
            {"input": " Фамилия ", "text": "Петров"}, {"click": "ОК", "closes": True}, {"message": "Готово"}]})
        self.assertEqual(steps, [
            {"index": 1, "kind": "input", "target": "Фамилия", "text": "Петров"},
            {"index": 2, "kind": "click", "target": "ОК", "closes": True},
            {"index": 3, "kind": "message", "target": "Готово"}])
        self.assertEqual(scenario77.steps({"steps": [{"check": "Флажок77", "checked": False}]})[0]["expect"], "checked")
        self.assertIsNone(scenario77.steps({"actions": "click:4152"}))

    def test_malformed_steps_are_refused_before_a_session(self):
        bad = [
            "click:4152", [], ["ОК"], [{"click": "ОК", "input": "Код", "text": "1"}], [{"press": "ОК"}],
            [{"click": "ОК", "text": "x"}], [{"click": ""}], [{"click": "ОК", "closes": "yes"}],
            [{"input": "Код"}], [{"input": "Код", "text": 5}], [{"input": "Код", "text": "a\nb"}],
            [{"check": "Код"}], [{"check": "Код", "text": "1", "enabled": True}], [{"value": "Код.Имя", "text": "1"}],
            [{"value": "Код"}], [{"message": "✓ не в cp1251"}], [{"click": "ОК", "closes": True}, {"check": "Код", "text": ""}],
        ]
        for steps in bad:
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                scenario77.steps({"steps": steps})
        with self.assertRaisesRegex(ValueError, "either steps or actions"):
            scenario77.steps({"steps": [{"click": "ОК"}], "actions": "click:4152"})
        with self.assertRaisesRegex(ValueError, "either steps or actions"):
            form.FormAdapter().commands({"steps": [{"click": "ОК"}], "click_id": 4152}, [])

    def test_elements_resolve_by_identifier_then_caption(self):
        steps = scenario77.steps({"steps": [
            {"click": "кнзаписать"}, {"click": "Закрыть"}, {"input": "Имя", "text": ""},
            {"check": "Итог:", "text": "1"}, {"check": "флажок77", "checked": True}, {"value": "Сумма", "text": "0"}]})
        resolved = scenario77.resolve(steps, DESCRIPTION)
        self.assertEqual([s.get("record_id") for s in resolved], [4153, 4152, 4155, 4157, 4156, None])
        self.assertEqual(resolved[4]["element_class"], "CHECKBOX")

    def test_unknown_ambiguous_and_wrong_class_elements_are_refused(self):
        for step, message in (({"click": "Удалить"}, "no element"), ({"input": "Кем", "text": "x"}, "2 elements"),
                              ({"input": "КнЗаписать", "text": "x"}, "needs 1CEDIT or BMASKED"),
                              ({"click": "Фамилия"}, "needs BUTTON or CHECKBOX"),
                              ({"check": "Фамилия", "checked": True}, "needs CHECKBOX")):
            with self.subTest(step=step), self.assertRaisesRegex(ValueError, "step 1 .*" + message):
                scenario77.resolve(scenario77.steps({"steps": [step]}), DESCRIPTION)

    def test_controller_gets_the_step_function_and_open_clears_its_messages(self):
        steps = scenario77.steps({"steps": [{"click": "ОК"}, {"value": "Фамилия", "text": "Петров"}]})
        text = scenario77.controller(form.CONTROLLER, steps)
        self.assertEqual(text.count("Функция Harness77Step(Номер77Шага, Протокол, Метка) Экспорт"), 1)
        self.assertLess(text.index("Функция Harness77Step("), text.index("Функция Harness77Ert("))
        self.assertIn('    Если Номер77Шага = 2 Тогда\n        Попытка\n'
                      '            Ответ77 = "value:" + Harness77Строка(Контекст77Формы.Фамилия);', text)
        self.assertNotIn("Номер77Шага = 1 ", text)
        self.assertIn('    Сообщения77.SaveToFile(Протокол);\n    Если Команда = "open" Тогда\n'
                      '        Сообщения77.Clear();\n    КонецЕсли;\n    Возврат Ответ77;', text)
        with self.assertRaisesRegex(ValueError, "controller layout"):
            scenario77.controller("Функция Harness77Ert(\n", steps)

    def test_client_serves_step_requests_while_it_waits(self):
        adapter = form.FormAdapter()
        adapter.commands({"steps": [{"click": "ОК"}]}, [])
        text = adapter.client("x\n" + form.CALL + "\n")
        self.assertIn('If command = "result" Then AwaitClick', text)
        self.assertIn('requestPath = fso.BuildPath(folder, "form-step-request")', text)
        self.assertIn('controller.Harness77Step(number,', text)
        self.assertIn('donePath = fso.BuildPath(folder, "form-click-done")', text)
        self.assertNotIn("__", text.replace("__DONE__", ""))
        plain = form.FormAdapter()
        plain.commands({}, [])
        self.assertNotIn("Harness77Step", plain.client("x\n" + form.CALL + "\n"))

    def test_answer_and_messages_are_read_back(self):
        self.assertEqual(scenario77.answer("value:a\\nb\\\\n"), {"value": "a\r\nb\\n"})
        self.assertEqual(scenario77.answer("value-error:Поле объекта не обнаружено (Сумма) "),
                         {"value_error": "Поле объекта не обнаружено (Сумма)"})
        self.assertEqual(scenario77.answer(""), {})
        self.assertEqual(scenario77.messages("Готово\r\nHARNESS77-STEP:r:step:2", "r:step:2"), (["Готово"], True))
        self.assertEqual(scenario77.messages("Готово", "r:step:2"), (["Готово"], False))

    def test_each_kind_of_step_is_judged(self):
        def judge(item, record, pending=(), form_open=True):
            return scenario77.judge(scenario77.steps({"steps": [item]})[0], record, list(pending), form_open)
        clicked = {"action": {"returned": True}, "round_trip": trip()}
        self.assertIsNone(judge({"click": "ОК"}, clicked))
        self.assertRegex(judge({"click": "ОК"}, {"action": {"returned": False, "message": "BM_CLICK"}}), "did not return")
        self.assertRegex(judge({"click": "ОК"}, {"action": {"refused": "the element is disabled"}}), "disabled")
        self.assertRegex(judge({"click": "ОК"}, {"action": {"returned": True}, "round_trip": {"returned": False,
                                                                                         "error": "no answer"}}),
                         "1C did not answer")
        self.assertRegex(judge({"click": "ОК"}, dict(clicked, round_trip=trip(complete=False))), "not saved")
        self.assertEqual(judge({"click": "ОК"}, dict(clicked, round_trip=trip(diagnostics=[
            {"line": 5, "message": "Деление на 0"}]))), "step 1 (click 'ОК'): 1C reported an error: line 5: Деление на 0")
        self.assertRegex(judge({"click": "ОК"}, clicked, form_open=False), "the form closed")
        self.assertRegex(judge({"click": "ОК", "closes": True}, clicked), "did not close")
        self.assertIsNone(judge({"click": "ОК", "closes": True}, clicked, form_open=False))
        checked = {"round_trip": trip(), "state": {"text": "Петров   ", "checked": True, "enabled": False,
                                                    "visible": True}}
        self.assertIsNone(judge({"check": "Фамилия", "text": "Петров"}, checked))
        self.assertIsNone(judge({"check": "Число77", "text": "12.50"}, dict(checked, state={"text": " 12.50"})))
        self.assertRegex(judge({"check": "Фамилия", "text": "Иванов"}, checked), "shows 'Петров   ', expected 'Иванов'")
        self.assertIsNone(judge({"check": "Флажок77", "checked": True}, checked))
        self.assertRegex(judge({"check": "Записать", "enabled": True}, checked), "enabled is False, expected True")
        self.assertRegex(judge({"check": "Фамилия", "text": ""}, {"round_trip": trip(), "state": {"error": "gone"}}),
                         "not read: gone")
        self.assertIsNone(judge({"value": "Имя", "text": "Пётр"}, {"round_trip": trip(value="Пётр  ")}))
        self.assertRegex(judge({"value": "Имя", "text": "Пётр"}, {"round_trip": trip(value="Иван")}), "is 'Иван'")
        self.assertRegex(judge({"value": "Имя", "text": "Пётр"}, {"round_trip": trip(value_error="нет поля")}),
                         "did not read the attribute: нет поля")
        self.assertIsNone(judge({"message": "Готово"}, {"round_trip": trip()}, [" Готово "]))
        self.assertRegex(judge({"message": "Готово"}, {"round_trip": trip()}, ["Иное"]), "no such message")
        self.assertIsNone(judge({"no_message": "Готово"}, {"round_trip": trip()}, ["Иное"], form_open=False))
        self.assertRegex(judge({"no_message": "Готово"}, {"round_trip": trip()}, ["Готово"]), "is there")

    def test_scenario_result_needs_every_step_and_a_closed_form(self):
        steps = scenario77.steps({"steps": [{"click": "ОК"}, {"click": "Закрыть", "closes": True}]})
        passed = [dict(steps[0], status="passed", issue=None, form_open=True),
                  dict(steps[1], status="passed", issue=None, form_open=False)]
        self.assertEqual(scenario77.judge_result(steps, passed, closed_by_controller=False), [])
        self.assertEqual(scenario77.judge_result(steps[:1], passed[:1], closed_by_controller=True), [])
        self.assertEqual(scenario77.judge_result(steps[:1], passed[:1], closed_by_controller=False),
                         ["the form was not closed"])
        self.assertEqual(scenario77.judge_result(steps, passed[:1], closed_by_controller=True), ["only 1 of 2 steps ran"])
        failed = [dict(passed[0], status="failed", issue="step 1 (click 'ОК'): x")]
        self.assertEqual(scenario77.judge_result(steps, failed, closed_by_controller=True), ["step 1 (click 'ОК'): x"])
        self.assertEqual(scenario77.judge_result(steps, None, closed_by_controller=True), ["only 0 of 2 steps ran"])


def window(text="", title="1С:Предприятие", captions=("OK",), fields=0, hwnd=100):
    """A modal window as form_window77.window_record reads it: static text, push buttons, input fields."""
    children = [{"hwnd": 1, "parent": hwnd, "class": "Static", "id": 20, "text": "", "style": 0x50000003}]
    if text:
        children.append({"hwnd": 2, "parent": hwnd, "class": "Static", "id": 65535, "text": text, "style": 0x50000080})
    for number, caption in enumerate(captions):
        children.append({"hwnd": 10 + number, "parent": hwnd, "class": "Button", "id": number + 1, "text": caption,
                         "visible": True, "enabled": True, "style": 0x50010000 | (number == 0)})
    for number in range(fields):
        children.append({"hwnd": 30 + number, "parent": hwnd, "class": "Edit", "id": 1000 + number, "text": "",
                         "style": 0x50010080})
    return {"hwnd": hwnd, "class": "#32770", "text": title, "children": children}


class DialogStepsTests(unittest.TestCase):
    """Task 026: modal windows an action opens, answered by the dialog steps after it."""

    def test_dialog_steps_chain_after_their_action(self):
        steps = scenario77.steps({"steps": [
            {"click": "Окно 77"}, {"dialog": " Записать? ", "button": " Да "},
            {"dialog": "Готово", "closes": True}, {"message": "конец"}]})
        self.assertEqual(steps[0], {"index": 1, "kind": "click", "target": "Окно 77", "dialogs": 2})
        self.assertEqual(steps[1], {"index": 2, "kind": "dialog", "target": "Записать?", "button": "Да",
                                    "chain": 1, "last": False})
        self.assertEqual(steps[2], {"index": 3, "kind": "dialog", "target": "Готово", "closes": True,
                                    "chain": 1, "last": True})
        steps = scenario77.steps({"steps": [{"input": "Число77", "text": "500"}, {"dialog": "Больше 100"},
                                            {"click": "ОК"}, {"dialog": "Строка", "text": "", "button": "ОК"}]})
        self.assertEqual([s.get("dialogs") for s in steps], [1, None, 1, None])
        self.assertEqual([(s.get("chain"), s.get("last")) for s in steps[1::2]], [(1, True), (3, True)])
        self.assertNotIn("dialogs", scenario77.steps({"steps": [{"click": "ОК"}]})[0])

    def test_dialog_steps_out_of_order_are_refused(self):
        for steps, message in (
                ([{"dialog": "Записать?"}], "follows the click or input"),
                ([{"check": "Код", "text": ""}, {"dialog": "Записать?"}], "follows the click or input"),
                ([{"click": "ОК"}, {"message": "x"}, {"dialog": "Записать?"}], "follows the click or input"),
                ([{"click": "ОК", "closes": True}, {"dialog": "Записать?"}], "step 1 .*put closes on the last dialog"),
                ([{"click": "ОК"}, {"dialog": "А", "closes": True}, {"dialog": "Б"}], "step 2 .*put closes"),
                ([{"click": "ОК"}, {"dialog": "А", "closes": True}, {"click": "ОК"}], "the form is closed at step 2"),
                ([{"click": "ОК"}, {"dialog": "А", "button": " "}], "button is the caption"),
                ([{"click": "ОК"}, {"dialog": "А", "button": 1}], "button must be a string"),
                ([{"click": "ОК"}, {"dialog": ""}], "non-empty"),
                ([{"click": "ОК"}, {"dialog": "А", "checked": True}], "unknown keys")):
            with self.subTest(steps=steps), self.assertRaisesRegex(ValueError, message):
                scenario77.steps({"steps": steps})
        resolved = scenario77.resolve(scenario77.steps({"steps": [{"click": "Закрыть"}, {"dialog": "А"}]}), DESCRIPTION)
        self.assertNotIn("record_id", resolved[1])

    def test_window_text_buttons_and_the_answer(self):
        question = window("Записать\r\nизменения?", captions=("&Да", "Нет", "Отмена"))
        self.assertEqual(scenario77.dialog_text(question), "Записать изменения?")
        self.assertEqual(scenario77.dialog_text(window("", title=" Harness77 строка ")), "Harness77 строка")

        def plan(step, shown):
            return scenario77.answer_plan(scenario77.steps({"steps": [{"click": "ОК"}, step]})[1], shown)
        button, field, issue = plan({"dialog": "Записать изменения?", "button": "да"}, question)
        self.assertEqual((button["hwnd"], field, issue), (10, None, None))
        self.assertEqual(plan({"dialog": "Записать  изменения?", "button": "Нет"}, question)[0]["text"], "Нет")
        self.assertEqual(plan({"dialog": "Записать?", "button": "Да"}, question)[2],
                         "the window shows 'Записать изменения?' with buttons ['Да', 'Нет', 'Отмена']")
        self.assertEqual(plan({"dialog": "Записать изменения?", "button": "Пропустить"}, question)[2],
                         "no button 'Пропустить' among ['Да', 'Нет', 'Отмена']")
        self.assertRegex(plan({"dialog": "Записать изменения?"}, question)[2], "name one with button")
        self.assertEqual(plan({"dialog": "Готово"}, window("Готово"))[0]["id"], 1)
        # «ОК» in Cyrillic presses the Latin «OK» of 1C's warning: a caption compares as it looks.
        self.assertEqual(plan({"dialog": "Готово", "button": "ОК"}, window("Готово", captions=("OK", "Cancel")))[0]["id"], 1)
        self.assertEqual(plan({"dialog": "Готово", "button": "Cancel"}, window("Готово", captions=("OK", "Сancel")))[0]["id"], 2)
        prompt = window("", title="Harness77 строка", captions=("OK", "Отмена"), fields=1)
        button, field, issue = plan({"dialog": "Harness77 строка", "text": "abc", "button": "ok"}, prompt)
        self.assertEqual((button["hwnd"], field["hwnd"], issue), (10, 30, None))
        self.assertRegex(plan({"dialog": "Готово", "text": "abc"}, window("Готово"))[2], "has 0 input fields")
        # A check box is a button of the window too, but not an answer; a grandchild is not the window's own.
        boxed = window("Готово")
        boxed["children"] += [{"hwnd": 50, "parent": 100, "class": "Button", "id": 9, "text": "Больше не спрашивать",
                               "visible": True, "enabled": True, "style": 0x50010003},
                              {"hwnd": 51, "parent": 50, "class": "Button", "id": 8, "text": "Вложенная"}]
        self.assertEqual(plan({"dialog": "Готово"}, boxed)[0]["hwnd"], 10)

    def test_a_window_no_step_expects_is_closed_with_the_safest_answer(self):
        self.assertEqual(scenario77.safe_button(window("?", captions=("Да", "Нет", "Отмена")))["text"], "Отмена")
        self.assertEqual(scenario77.safe_button(window("?", captions=("Да", "Нет")))["text"], "Нет")
        self.assertEqual(scenario77.safe_button(window("!", captions=("OK",)))["text"], "OK")
        self.assertEqual(scenario77.safe_button(window("?", captions=("Повтор", "Cancel")))["text"], "Cancel")
        self.assertEqual(scenario77.safe_button(window("?", captions=("Прервать", "Повтор")))["id"], 2)
        self.assertIsNone(scenario77.safe_button(window("?", captions=())))

    def test_the_calls_of_a_chain_are_judged_as_one(self):
        # m-close, series 0c: #Закрыть returned at once and 1C asked while it was asked itself; the chain then asks
        # again after the answer, under its own number, and the last step judges every call.
        self.assertEqual([scenario77.trip_number(3, n) for n in range(3)], [3, 1003, 2003])
        merged = scenario77.merge_trips([trip(messages=["до"], number=2),
                                         trip(messages=["после"], diagnostics=[{"line": 4, "message": "x"}])])
        self.assertEqual(merged, {"returned": True, "complete": True, "messages": ["до", "после"],
                                  "diagnostics": [{"line": 4, "message": "x"}], "calls": 2})
        self.assertEqual(scenario77.merge_trips([trip(), {"returned": False, "error": "no answer in 30 s"}]),
                         {"returned": False, "complete": False, "messages": [], "diagnostics": [], "calls": 2,
                          "error": "no answer in 30 s"})
        self.assertFalse(scenario77.merge_trips([])["returned"])
        steps = scenario77.steps({"steps": [{"click": "Закрыть"}, {"dialog": "Записать?", "button": "Да", "closes": True}]})
        record = dict(steps[1], window=window("Записать?", captions=("Да", "Нет")), answer={"requested": True},
                      action={"returned": True}, round_trip=merged)
        self.assertRegex(scenario77.judge(steps[1], record, merged["messages"], False), "1C reported an error: line 4")

    def test_the_watcher_keeps_the_methods_of_its_thread(self):
        # Series 0: a watcher method named start replaced Thread.start, and no session got its watcher.
        import threading
        for name in ("start", "join", "is_alive", "name", "daemon"):
            self.assertIs(getattr(form.FormWatcher, name), getattr(threading.Thread, name), name)
        public = {name for name in dir(threading.Thread) if not name.startswith("_")} - {"run"}
        self.assertEqual(set(vars(form.FormWatcher)) & public, set())

    def test_dialog_steps_are_judged(self):
        steps = scenario77.steps({"steps": [{"click": "Окно 77"}, {"dialog": "Записать?", "button": "Да"},
                                            {"dialog": "Готово", "closes": True}]})
        click, first, last = steps
        shown = window("Записать?", captions=("Да", "Нет"))
        self.assertIsNone(scenario77.judge(click, {"action": {"returned": None}, "modal": shown}, [], True))
        self.assertEqual(scenario77.judge(dict(click, dialogs=0), {"action": {}, "unexpected": shown}, [], True),
                         "step 1 (click 'Окно 77'): an unexpected modal window 'Записать?' with buttons ['Да', 'Нет']")
        # The action returned without a window: it passes, and its dialog step fails.
        self.assertIsNone(scenario77.judge(click, {"action": {"returned": True}, "round_trip": trip()}, [], True))
        self.assertEqual(scenario77.judge(first, {"window": None}, [], True),
                         "step 2 (dialog 'Записать?'): no modal window opened")
        self.assertRegex(scenario77.judge(first, {"window": shown, "answer": {"refused": "the window shows 'x'"}}, [],
                                          True), r"step 2 .*: the window shows 'x'")
        self.assertRegex(scenario77.judge(first, {"window": shown, "answer": {"error": "type did not return"}}, [],
                                          True), "not answered: type did not return")
        answered = {"window": shown, "answer": {"requested": True}}
        self.assertIsNone(scenario77.judge(first, dict(answered, modal=window("Готово")), [], True))
        # The last window ends the action: it returned, 1C answered, the form closed as declared.
        ended = dict(answered, action={"returned": True, "message": "BM_CLICK"}, round_trip=trip())
        self.assertIsNone(scenario77.judge(last, ended, [], False))
        self.assertRegex(scenario77.judge(last, ended, [], True), "the form did not close")
        self.assertRegex(scenario77.judge(dict(last, closes=False), ended, [], False), "the form closed")
        self.assertEqual(scenario77.judge(last, dict(ended, action={"returned": False, "message": "BM_CLICK"}), [], True),
                         "step 3 (dialog 'Готово'): BM_CLICK did not return after the window closed")
        self.assertEqual(scenario77.judge(last, dict(ended, action={"returned": False, "failed_stage": "leave",
                                                                    "reason": "the field kept the focus"}), [], True),
                         "step 3 (dialog 'Готово'): leave failed after the window closed: the field kept the focus")
        self.assertRegex(scenario77.judge(last, dict(ended, round_trip=trip(diagnostics=[
            {"line": 7, "message": "Деление на 0"}])), [], False), "1C reported an error: line 7")
        self.assertRegex(scenario77.judge(last, dict(answered, unexpected=window("Ещё")), [], True),
                         "step 3 .*an unexpected modal window 'Ещё'")
        # The launcher's record is the step with what happened (series 0b: a key of the step hid the action's outcome).
        self.assertNotIn("action", first)
        self.assertEqual(scenario77.judge(first, dict(first, window=None), [], True),
                         "step 2 (dialog 'Записать?'): no modal window opened")
        self.assertIsNone(scenario77.judge(first, dict(first, **answered, modal=window("Готово")), [], True))
        records = [dict(click, status="passed", issue=None), dict(first, status="passed", issue=None),
                   dict(last, status="passed", issue=None, form_open=False)]
        self.assertEqual(scenario77.judge_result(steps, records, closed_by_controller=False), [])


class StepOperationTests(unittest.TestCase):
    """The launcher judges commands of a scenario without the harness protocol of the form."""

    def adapter(self, inspection):
        adapter = form.FormAdapter()
        adapter.commands({"steps": [{"click": "ОК"}]}, [])
        adapter.evidence = lambda: (inspection, {"controls": []})
        return adapter

    def row(self, diagnostics=()):
        return {"name": "x", "status": "blocked", "value": None, "diagnostics": list(diagnostics)}

    def test_check_needs_no_loaded_marker_but_fails_on_a_1c_error(self):
        lines = ["selected:x", "open-return:1", "closed:1"]
        row = self.row()
        self.assertIsNone(self.adapter({}).operation("check", lines, "\n".join(lines), row))
        self.assertEqual((row["status"], row["value"]), ("passed", "1"))
        row = self.row([{"line": 3, "message": "Деление на 0"}])
        self.adapter({}).operation("check", lines, "\n".join(lines), row)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["form_issues"], ["1C reported an error: line 3: Деление на 0"])

    def test_result_reports_the_steps(self):
        record = {"index": 1, "kind": "click", "target": "ОК", "status": "passed", "issue": None, "form_open": True}
        lines = ["selected:x", "closed:1"]
        row = self.row()
        self.adapter({"found": True, "steps": [record]}).operation("result", lines, "\n".join(lines), row)
        self.assertEqual((row["status"], row["steps"], row["form_issues"]), ("passed", [record], []))
        row = self.row()
        failed = dict(record, status="failed", issue="step 1 (click 'ОК'): the form closed")
        self.adapter({"found": True, "steps": [failed]}).operation("result", ["selected:x", "close-error:x"], "", row)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["form_issues"], ["step 1 (click 'ОК'): the form closed", "the form was not closed"])
        row = self.row()
        self.adapter({"found": False, "reason": "no window"}).operation("result", lines, "\n".join(lines), row)
        self.assertEqual(row["form_issues"], ["inspection: no window", "only 0 of 1 steps ran"])


# The document form of «Готовая продукция» (task 027): its table part after 6 windows, five columns.
TABLE = {"position": 6, "columns": 5, "document": True, "fields": [
    {"identifier": "НомерСтроки", "caption": "N", "class": "1CEDIT", "formula": "", "window_id": 4158, "type": None},
    {"identifier": "Товар", "caption": "Наименование", "class": "BMASKED", "formula": "Пересчет()", "window_id": 4159,
     "type": "B"},
    {"identifier": "Количество", "caption": "Кол-во", "class": "1CEDIT", "formula": "Пересчет()", "window_id": 4160,
     "type": "N"},
    {"identifier": "", "caption": "Вид", "class": "STATIC", "formula": "Вид()", "window_id": 4161},
    {"identifier": "Сумма", "caption": "Сумма", "class": "1CEDIT", "formula": "Пересчет()", "window_id": 4162,
     "type": "N"}]}


def table_steps(*items, table=TABLE):
    return scenario77.resolve(scenario77.steps({"steps": list(items)}), dict(DESCRIPTION, browser=table))


class TableStepsTests(unittest.TestCase):
    def test_table_steps_are_read(self):
        steps = scenario77.steps({"steps": [
            {"add_row": True}, {"cell": " Кол-во ", "text": "3"}, {"row": 2}, {"rows": 0}, {"delete_row": True},
            {"total": "Сумма", "text": "30"}, {"value": "Сумма", "row": 1, "text": "30"}, {"key": "pagedown"},
            {"key": "F9", "closes": True}]})
        self.assertEqual([(s["kind"], s["target"]) for s in steps], [
            ("add_row", "add_row"), ("cell", "Кол-во"), ("row", 2), ("rows", 0), ("delete_row", "delete_row"),
            ("total", "Сумма"), ("value", "Сумма"), ("key", "PageDown"), ("key", "F9")])
        self.assertEqual(steps[6]["row"], 1)
        self.assertEqual([scenario77.label(s) for s in steps[:3]],
                         ["step 1 (add_row)", "step 2 (cell 'Кол-во')", "step 3 (row 2)"])
        self.assertEqual(scenario77.KEYS["f9"], ("F9", 0x78, False))
        self.assertEqual(scenario77.KEYS["delete"], ("Delete", 0x2E, True))

    def test_malformed_table_steps_are_refused(self):
        for item in ({"add_row": False}, {"add_row": "yes"}, {"delete_row": 1}, {"row": 0}, {"row": "1"},
                     {"row": True}, {"rows": -1}, {"row": 100000}, {"cell": "Сумма"}, {"total": "Сумма"},
                     {"key": "Space"}, {"key": ""}, {"value": "Сумма", "row": 0, "text": "1"},
                     {"value": "Сумма", "row": "1", "text": "1"}, {"add_row": True, "text": "1"}):
            with self.subTest(item=item), self.assertRaises(ValueError):
                scenario77.steps({"steps": [item]})
        # Dialog steps follow the table's actions as they follow a click (task 026).
        steps = scenario77.steps({"steps": [{"delete_row": True}, {"dialog": "Удалить?", "button": "Да"}]})
        self.assertEqual((steps[0]["dialogs"], steps[1]["chain"]), (1, 1))

    def test_columns_resolve_by_identifier_then_caption(self):
        steps = table_steps({"cell": "кол-во", "text": "3"}, {"cell": "Сумма", "text": "x"}, {"total": "сумма", "text": "1"},
                            {"add_row": True}, {"key": "Down"})
        self.assertEqual([(s.get("column"), s.get("column_window")) for s in steps],
                         [("Количество", 4160), ("Сумма", 4162), ("Сумма", 4162), (None, None), (None, None)])
        for item, message in (({"cell": "Цена", "text": "1"}, "no column"),
                              ({"cell": "N", "text": "1"}, "needs a field of an attribute"),
                              ({"cell": "Вид", "text": "1"}, "is STATIC"),
                              ({"total": "Вид", "text": "1"}, "no attribute to total"),
                              ({"cell": "Товар", "text": "x"}, r"holds a reference \(B\)")):
            with self.subTest(item=item), self.assertRaisesRegex(ValueError, "step 1 .*" + message):
                table_steps(item)
        twice = dict(TABLE, fields=TABLE["fields"] + [dict(TABLE["fields"][2], identifier="Количество2")])
        with self.assertRaisesRegex(ValueError, "2 columns match"):
            table_steps({"cell": "Кол-во", "text": "1"}, table=twice)

    def test_table_steps_need_a_document_form_with_a_table_part(self):
        for item in ({"add_row": True}, {"row": 1}, {"value": "Сумма", "row": 1, "text": "1"}, {"key": "Down"}):
            with self.subTest(item=item), self.assertRaisesRegex(ValueError, "has no table part"):
                scenario77.resolve(scenario77.steps({"steps": [item]}), DESCRIPTION)
        listed = dict(TABLE, document=False)
        self.assertEqual(table_steps({"key": "Down"}, {"value": "Наименование", "text": "x"}, table=listed)[0]["target"],
                         "Down")
        for item in ({"add_row": True}, {"rows": 1}, {"value": "Сумма", "row": 1, "text": "1"}):
            with self.subTest(item=item), self.assertRaisesRegex(ValueError, "a list takes key steps"):
                table_steps(item, table=listed)

    def test_the_controller_works_the_table_part_on_the_steps_own_call(self):
        steps = table_steps({"add_row": True}, {"cell": "Кол-во", "text": "3"}, {"row": 2},
                            {"total": "Сумма", "text": "30"}, {"value": "Сумма", "row": 1, "text": "30"},
                            {"value": "Товар", "text": "x"})
        text = scenario77.controller(form.CONTROLLER, steps, table=True)
        self.assertIn('    Ответ77 = Ответ77 + Harness77Таблица();\n    Сообщить("HARNESS77-STEP:" + Метка);', text)
        self.assertIn('"rows:" + Строка(Контекст77Формы.КоличествоСтрок())', text)
        self.assertIn('"column:" + Harness77Строка(Контекст77Формы.Форма.ТекущаяКолонка())', text)
        self.assertNotIn("Номер77Шага = 1 ", text)
        self.assertIn('    Если Номер77Шага = 2 Тогда\n        Попытка\n'
                      '            Контекст77Формы.Активизировать("Количество", 1);\n', text)
        # The keys move the row (series 1e); the controller only refuses a row the table lacks.
        self.assertNotIn("АктивизироватьСтроку", text)
        self.assertIn('"error:no row 2 of " + Строка(Контекст77Формы.КоличествоСтрок())', text)
        self.assertIn('Ответ77 = "total:" + Harness77Строка(Контекст77Формы.Итог("Сумма"));', text)
        self.assertIn('Контекст77Формы.ВыгрузитьТабличнуюЧасть(Таблица77, "Сумма");', text)
        self.assertIn('Ответ77 = "value:" + Harness77Строка(Таблица77.ПолучитьЗначение(1, "Сумма"));', text)
        self.assertIn('Ответ77 = "value:" + Harness77Строка(Контекст77Формы.Товар);', text)
        self.assertNotIn("Harness77Таблица", scenario77.controller(form.CONTROLLER, steps[-1:]))

    def test_the_state_of_the_table_part_is_read_back(self):
        self.assertEqual(scenario77.answer("\r\nrows:2\r\nrow:1\r\ncolumn:Количество "),
                         {"rows": 2, "row": 1, "column": "Количество"})
        self.assertEqual(scenario77.answer("total: 30.00\r\nrows:x\r\nstate-error:Нет\\nстрок"),
                         {"total": " 30.00", "state_error": "Нет\r\nстрок"})
        self.assertEqual(scenario77.answer("error:no row 3 of 2\r\nrows:2\r\nother:1"),
                         {"table_error": "no row 3 of 2", "rows": 2})
        self.assertEqual(scenario77.answer("value:a:b\r\nrow:1"), {"value": "a:b", "row": 1})
        merged = scenario77.merge_trips([trip(rows=1, row=1, column="Товар", messages=["a"]),
                                         trip(rows=2, row=2, messages=["b"])])
        self.assertEqual((merged["rows"], merged["row"], "column" in merged, merged["messages"]), (2, 2, False, ["a", "b"]))

    def test_table_steps_are_judged(self):
        def judge(item, record):
            return scenario77.judge(table_steps(item)[0], record, [], True)
        added = {"action": {"returned": True}, "before": trip(rows=1, row=1), "round_trip": trip(rows=2, row=2)}
        self.assertIsNone(judge({"add_row": True}, added))
        self.assertEqual(judge({"add_row": True}, dict(added, round_trip=trip(rows=1, row=1))),
                         "step 1 (add_row): the table has 1 rows, expected 2")
        self.assertRegex(judge({"add_row": True}, dict(added, before=trip())), "not read before the step")
        self.assertRegex(judge({"add_row": True}, dict(added, round_trip=trip(state_error="Нет"))), "not read: Нет")
        self.assertIsNone(judge({"delete_row": True}, dict(added, before=trip(rows=3, row=1))))
        self.assertRegex(judge({"delete_row": True}, added), "has 2 rows, expected 0")
        cell = {"action": {"returned": True, "committed": True}, "round_trip": trip(rows=1, row=1)}
        self.assertIsNone(judge({"cell": "Кол-во", "text": "3"}, cell))
        self.assertRegex(judge({"cell": "Кол-во", "text": "3"}, dict(cell, action={"returned": True})),
                         "kept its editor after Enter")
        self.assertRegex(judge({"cell": "Кол-во", "text": "3"}, {"action": {
            "refused": "column 'Количество' did not become current: 'Товар'"}}), "did not become current")
        self.assertRegex(judge({"cell": "Кол-во", "text": "3"}, dict(cell, round_trip=trip(table_error="Нет поля"))),
                         "1C refused: Нет поля")
        self.assertIsNone(judge({"row": 2}, {"round_trip": trip(rows=2, row=2)}))
        self.assertRegex(judge({"row": 2}, {"round_trip": trip(rows=2, row=1)}), "the current row is 1, expected 2")
        # A new row's input ends before the cursor moves (series 1, r-rows): an editor that stays open fails the step.
        self.assertRegex(judge({"row": 1}, {"input_ended": False, "round_trip": trip(rows=2, row=2)}),
                         "the row's input did not end")
        self.assertIsNone(judge({"row": 1}, {"input_ended": True, "round_trip": scenario77.merge_trips(
            [trip(rows=2, row=2, messages=["пересчет"]), trip(rows=2, row=1)])}))
        self.assertRegex(judge({"row": 3}, {"round_trip": scenario77.merge_trips(
            [trip(rows=2, row=2), trip(rows=2, row=2, table_error="no row 3 of 2")])}), "1C refused: no row 3 of 2")
        self.assertRegex(judge({"row": 3}, {"round_trip": trip(rows=2, row=1, table_error="no row 3 of 2")}),
                         "1C refused: no row 3 of 2")
        self.assertIsNone(judge({"rows": 2}, {"round_trip": trip(rows=2, row=1)}))
        self.assertRegex(judge({"rows": 1}, {"round_trip": trip(rows=2, row=1)}), "has 2 rows, expected 1")
        self.assertIsNone(judge({"total": "Сумма", "text": "30"}, {"round_trip": trip(total=" 30 ", rows=1, row=1)}))
        self.assertRegex(judge({"total": "Сумма", "text": "30"}, {"round_trip": trip(total="20")}), "is '20', expected '30'")
        self.assertRegex(judge({"total": "Сумма", "text": "30"}, {"round_trip": trip()}), "no total")
        self.assertIsNone(judge({"value": "Сумма", "row": 1, "text": "30"}, {"round_trip": trip(value="30")}))
        self.assertRegex(judge({"value": "Сумма", "row": 2, "text": "30"},
                               {"round_trip": trip(value_error="no row 2 of 1")}),
                         "did not read the attribute: no row 2 of 1")
        self.assertIsNone(judge({"key": "Down"}, {"action": {"returned": True}, "round_trip": trip()}))


if __name__ == "__main__":
    unittest.main()
