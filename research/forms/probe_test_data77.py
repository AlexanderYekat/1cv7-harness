"""Task 024 native acceptance, expectations in docs/tasks/024-test-data.md.

Reuse the task 022 series runner: each case builds and opens a fresh configuration
copy, records operations and form evidence, verifies the source base and base list.
"""
import argparse
import copy
from pathlib import Path

import probe_md_forms77 as base
from probe_md_catalogs77 import BANKS_ELEMENT, BANKS_GROUP, button, case

SCOPE = "task 024: prepared test data and existing object forms on a base copy"

BANK = '''Спр77 = СоздатьОбъект("Справочник.Банки");
Спр77.Новый();
Спр77.УстановитьНовыйКод("77");
Спр77.Наименование = "Harness77 банк 024";
Спр77.Записать();
Возврат Спр77.ТекущийЭлемент();'''
GROUP = BANK.replace("Спр77.Новый();", "Спр77.НоваяГруппа();").replace("банк 024", "группа 024")
DOCUMENT = '''Док77 = СоздатьОбъект("Документ.Доверенность");
Док77.Новый();
Док77.ДатаДок = '23.10.2026';
Док77.УстановитьНовыйНомер("77");
Док77.Комментарий = "Harness77 документ 024";
Док77.Записать();
Возврат Док77.ТекущийДокумент();'''
OWNER = BANK.replace("Справочник.Банки", "Справочник.Контрагенты").replace("банк 024", "владелец 024")
CHILD = OWNER.replace("Возврат Спр77.ТекущийЭлемент();", '''Договор77 = СоздатьОбъект("Справочник.Договоры");
Договор77.ИспользоватьВладельца(Спр77.ТекущийЭлемент());
Договор77.Новый();
Договор77.УстановитьНовыйКод("77");
Договор77.Наименование = "Harness77 договор 024";
Договор77.Записать();
Возврат Договор77.ТекущийЭлемент();''')
VERIFY_BANK = '''Спр77 = СоздатьОбъект("Справочник.Банки");
Если Спр77.НайтиЭлемент(Объект77) <> 1 Тогда Возврат "not found"; КонецЕсли;
Возврат СокрЛП(Спр77.Наименование);'''
OPEN_NAME = base.OPEN_PLAIN + '\n    Harness77Добавить("initial:" + СокрЛП(Наименование));'
OPEN_OWNER = base.OPEN_PLAIN + '\n    Harness77Добавить("owner:" + СокрЛП(Владелец.Наименование));'

CASES = [
    case("element", BANKS_ELEMENT, opening=OPEN_NAME, parameters={"fixture_setup": BANK},
         open="passed", result="passed", value="initial:Harness77 банк 024", fields_open={4166: "Harness77 банк 024"}),
    case("group", BANKS_GROUP, opening=OPEN_NAME, parameters={"fixture_setup": GROUP},
         open="passed", result="passed", value="initial:Harness77 группа 024", fields_open={4155: "Harness77 группа 024"}),
    case("document", base.DOCUMENT, opening=base.OPEN_PLAIN + '\n    Harness77Добавить("initial:" + СокрЛП(Комментарий));',
         closing=base.CLOSE_DOCUMENT, parameters={"fixture_setup": DOCUMENT}, open="passed", result="passed",
         change=base.grown(240, [button(180, 222)]), actions="click:4191",
         values='    Harness77Добавить("comment:" + СокрЛП(Комментарий));\n',
         value="initial:Harness77 документ 024;clicked:1;comment:Harness77 документ 024",
         fields_open={4163: "Harness77 документ 024"}),
    case("child", "Справочник/Договоры/ФормаЭлемента", opening=OPEN_OWNER,
         parameters={"fixture_setup": CHILD}, open="passed", result="passed", value="owner:Harness77 владелец 024",
         fields_open={4165: "Harness77 договор 024"}),
    case("owner", "Справочник/Договоры/ФормаЭлемента", opening=OPEN_OWNER,
         parameters={"fixture_setup": OWNER, "fixture_mode": "owner"},
         open="passed", result="passed", value="owner:Harness77 владелец 024"),
    case("example", BANKS_ELEMENT, opening=OPEN_NAME,
         change=base.grown(210, [button(180, 155), base.control(**{
             "class": "1CEDIT", "identifier": "НовоеИмя77", "type": {"kind": "string", "length": 100},
             "x": 10, "y": 180, "width": 222, "height": 13})]),
         actions="type:4168=Harness77 изменено 024,click:4167",
         values='    Наименование = НовоеИмя77; Записать();\n    Harness77Добавить("saved:" + СокрЛП(Наименование));\n',
         parameters={"fixture_setup": BANK, "fixture_verify": VERIFY_BANK},
         open="passed", result="passed", value="initial:Harness77 банк 024;clicked:1;saved:Harness77 изменено 024",
         verify_value="Harness77 изменено 024", fields_open={4166: "Harness77 банк 024"}),
    case("wrong-kind", BANKS_ELEMENT, parameters={"fixture_setup": OWNER}, open="failed", result="failed", value=None,
         blocked="reference kind does not match"),
    case("wrong-group", BANKS_ELEMENT, parameters={"fixture_setup": GROUP}, open="failed", result="failed", value=None,
         blocked="reference group flag does not match"),
    case("empty", BANKS_ELEMENT, parameters={"fixture_setup": 'Спр77 = СоздатьОбъект("Справочник.Банки");\nВозврат Спр77.ТекущийЭлемент();'},
         open="failed", result="failed", value=None, blocked="empty or unwritten reference"),
    case("setup-error", BANKS_ELEMENT, parameters={"fixture_setup": 'Делитель77 = 0; Возврат 1 / Делитель77;'},
         open="failed", result="failed", value=None, blocked="fixture_setup_failed"),
]
example = next(c for c in CASES if c["id"] == "example")
CASES.append(dict(copy.deepcopy(example), id="example-repeat"))
CASES.append(dict(copy.deepcopy(example), id="wrong-expectation", verify_value="intentionally wrong", wrong_expectation=True))
CASES.append(case("unwritten", BANKS_ELEMENT, parameters={"fixture_setup": BANK.replace("Спр77.Записать();", "")},
                  open="failed", result="failed", value=None, blocked="empty or unwritten reference"))
CASES.append(case("wrong-owner", "Справочник/Договоры/ФормаЭлемента",
                  parameters={"fixture_setup": BANK, "fixture_mode": "owner"}, open="failed", result="failed",
                  value=None, blocked="reference kind does not match"))
verify_error = dict(copy.deepcopy(example), id="verify-error", verify_error=True)
verify_error["parameters"]["fixture_verify"] = "Делитель77 = 0; Возврат 1 / Делитель77;"
CASES.append(verify_error)
verify_negative = dict(copy.deepcopy(verify_error), id="verify-negative", verify_value=None, verify_expect="failed")
del verify_negative["verify_error"]
CASES.append(verify_negative)
once = dict(copy.deepcopy(example), id="setup-once", verify_value="Harness77 изменено 024;count:1")
once["parameters"]["fixture_verify"] = VERIFY_BANK.replace("Возврат СокрЛП(Спр77.Наименование);", '''Имя77 = СокрЛП(Спр77.Наименование);
Число77 = 0;
Спр77.ВыбратьЭлементы();
Пока Спр77.ПолучитьЭлемент() = 1 Цикл
    Если (СокрЛП(Спр77.Наименование) = "Harness77 банк 024") ИЛИ (СокрЛП(Спр77.Наименование) = "Harness77 изменено 024") Тогда
        Число77 = Число77 + 1;
    КонецЕсли;
КонецЦикла;
Возврат Имя77 + ";count:" + СокрЛП(Строка(Число77));''')
CASES.append(once)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stand", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=base.ROOT / ".artifacts/runs")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.baselines = None
    if args.evidence.exists():
        parser.error("evidence already exists")
    if set(args.case) - {c["id"] for c in CASES}:
        parser.error("unknown case")
    cases = [copy.deepcopy(c) for c in CASES if not args.case or c["id"] in args.case]
    return base.dry_run(cases, args) if args.dry_run else base.run_series(cases, args, SCOPE)


if __name__ == "__main__":
    raise SystemExit(main())
