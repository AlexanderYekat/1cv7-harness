"""Task 039: native journal copy with separate source and saved-copy identities."""
import journal77

# Set from the platform menu resource and verified against the live native menu.
COPY_COMMAND = 0x8016  # 1crcrus.dll menus 135/253: Копировать (F9)


def validate(parameters, previous):
    journal77.validate(parameters, parameters.get('form_object'))
    if (parameters.get('fixture_mode') != 'journal_existing'
            or not previous or previous[-1]['kind'] != 'find_document'
            or previous[-1].get('open') is not False):
        raise ValueError('journal_copy requires an immediately preceding find_document open=false')


def checked_new(trip):
    if (not trip.get('returned') or not trip.get('complete') or trip.get('diagnostics')
            or trip.get('journal_error') or trip.get('journal_new') != '1'
            or trip.get('journal_copy') != '1' or not trip.get('journal_source')
            or not trip.get('journal_hwnd') or not trip.get('journal_value')
            or not trip.get('journal_date') or trip.get('journal_posted') != '0'
            or trip.get('journal_deleted') != '0' or 'journal_number' not in trip):
        raise RuntimeError('new unsaved copy/source/state was not independently verified')


def body(kind):
    return f'''            Сервис77 = СоздатьОбъект("Сервис");
            Новый77Контекст = 0;
            Если Сервис77.АктивныйКонтекст(Новый77Контекст) <> 1 Тогда
                Возврат "journal-error:no active copy context";
            КонецЕсли;
            Ссылка77 = Новый77Контекст.ТекущийДокумент();
            Если (ТипЗначенияСтр(Ссылка77) <> "Документ") ИЛИ (ВРег(Ссылка77.Вид()) <> ВРег("{kind}")) Тогда
                Возврат "journal-error:copied document kind mismatch";
            КонецЕсли;
            Если Ссылка77.Выбран() <> 0 Тогда Возврат "journal-error:copy was already saved"; КонецЕсли;
            Объект77Источник = Объект77Данных;
            Контекст77Формы = Новый77Контекст;
            Дата77Копии = Контекст77Формы.ДатаДок;
            Номер77Копии = Контекст77Формы.НомерДок;
            Расш77 = СоздатьОбъект("РасширениеФормы");
            Расш77.УстановитьФорму(Контекст77Формы.Форма);
            Ответ77 = "journal-new:1" + РазделительСтрок + "journal-copy:1" + РазделительСтрок
                + "journal-source:" + Harness77Строка(Объект77Источник) + РазделительСтрок
                + "journal-hwnd:" + Строка(Расш77.Дескриптор) + РазделительСтрок
                + "journal-date:" + Harness77ДатаИнтервала(Контекст77Формы.ДатаДок) + РазделительСтрок
                + "journal-number:" + СокрЛП(Контекст77Формы.НомерДок) + РазделительСтрок
                + "journal-posted:" + Строка(Контекст77Формы.Проведен()) + РазделительСтрок
                + "journal-deleted:" + Строка(Контекст77Формы.ПометкаУдаления()) + РазделительСтрок
                + "journal-value:" + Harness77ПроверитьДанные(Объект77Источник);
'''
