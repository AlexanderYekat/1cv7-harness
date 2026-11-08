"""Task 038: native journal deletion mark toggle; no programmatic mutation."""
import journal77
import scenario77

DELETE_COMMAND = 0x8011  # 1crcrus.dll menus 135/253: Удалить (Del)
MARK_QUESTION = 'Объект будет помечен на удаление !'
UNMARK_QUESTION = 'Подтвердите отмену удаления объекта !'


def checked_state(trip, inspection):
    journal77.checked_cursor(trip, inspection)
    if trip.get('journal_deleted') not in ('0', '1'):
        raise RuntimeError('saved deletion mark was not independently verified')


def answer(window, deleted, cancel=False):
    question = MARK_QUESTION if deleted else UNMARK_QUESTION
    if window.get('class') != '#32770' or scenario77.dialog_text(window) != question:
        raise RuntimeError('unexpected native deletion confirmation')
    button, _, issue = scenario77.answer_plan(dict(target=question, button='Нет' if cancel else 'Да'), window)
    if issue or button.get('id') != (7 if cancel else 6):
        raise RuntimeError(issue or 'native deletion answer button identity differs')
    return button
