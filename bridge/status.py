"""Progress messages for the optional, non-activating desktop status panel."""
import os,subprocess,sys,time
from pathlib import Path
from .core import ROOT,write_json,read_json

MESSAGES={
 'capture':('Получаем данные сражения','HOI4 на паузе. Это может занять несколько секунд.'),
 'generate':('Готовим тактический бой','Подбираем карту, войска и оснащение.'),
 'open':('Открываем Men of War','Дождитесь загрузки — переключение произойдёт автоматически.'),
 'restart':('Обновляем карту или сложность — перезапускаем Men of War','Игра закрывается из меню и откроется снова, чтобы новые ресурсы загрузились без конфликта с предыдущими.'),
 'verify':('Проверяем загруженный бой','Сверяем миссию и состав войск.'),
 'manual':('Ожидаем запуск миссии','Откройте в Men of War нашу кампанию и начните подготовленный бой. Мост продолжает ждать.'),
 'game_unavailable':('Men of War закрыта или произошёл вылет','Бой сохранён в мосте. Перезапустите Men of War. Вылет не считается поражением и сам по себе не списывает потери.'),
 'rejected':('Нельзя запустить второй бой','Уже идёт сражение в Men of War. Сначала завершите текущий бой.'),
 'loaded':('Бой готов','Можно командовать войсками в Men of War.'),
 'return':('Переносим результат в HOI4','Учитываем потери и отступление. HOI4 остаётся на паузе.'),
 'done':('Результат перенесён','Вернитесь в HOI4. Игра остаётся на паузе.'),
 'error':('Переход остановлен','Причина и подробности указаны ниже.'),
}


def friendly_error(error):
    text=str(error).lower()
    if 'finished tactical result could not be verified' in text:return 'Бой завершён, но проверка итоговых потерь не прошла. Результат сохранён; не перезапускайте миссию. Подробности указаны в окне моста.'
    if 'tactical transition is already active' in text:return 'Уже идёт сражение в Men of War. Сначала завершите текущий бой. Чтобы отменить его, сначала выйдите в меню Men of War.'
    if 'leave the completed mow mission' in text:return 'Предыдущий бой завершён. Выйдите из его миссии в меню Men of War, затем выберите новый бой.'
    if 'foreground focus' in text:return 'Окно игры перестало быть активным. Откройте его и проверьте сообщение в окне моста.'
    if 'escape' in text:return 'Переход остановлен клавишей Esc.'
    if 'native hoi4' in text:return 'Не удалось связаться с HOI4. Проверьте, что она запущена через мост.'
    if 'uniquely identify' in text:return 'Найдено несколько сражений. Пока не удалось определить выбранный бой.'
    if 'already applied' in text or 'return was started' in text:return 'Перенос уже выполнялся. Повтор остановлен, чтобы не списать потери дважды.'
    return 'Не удалось завершить переход. Подробности сохранены в окне и журнале моста.'


def manual_mission_message(session):
    fallback=MESSAGES['manual'][1]
    if not session:return fallback
    try:
        folder=Path(session);manifest=read_json(folder/'mission_manifest.json')
        source=manifest.get('source_map','');virtual=manifest.get('mission_path','')
        if not source or not virtual:return fallback
        label=source.rsplit('/',1)[-1] if '/map_' in virtual else None
        if not label:
            battle=read_json(folder/'battle.json')
            label=battle['attacker']['country']+' против '+battle['defender']['country']
        return ('Выйдите в главное меню MoW → одиночные миссии → «HOI4 — Men of War» → «'+label+
                '». Начните миссию. Кнопку в HOI4 повторно не нажимайте; мост ждёт этот бой.')
    except (OSError,ValueError,KeyError,TypeError):return fallback


class TransferStatus:
    def __init__(self,path=None):
        self.path=Path(path) if path else ROOT/'runtime/transfer-status.json'
        self.session=None;self.started=None;self.process=None

    def start_panel(self):
        if os.name!='nt':return
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            write_json(self.path,{'phase':'idle','visible':False})
            self.process=subprocess.Popen([sys.executable,'-m','bridge.status_panel',
                '--state',str(self.path),'--parent',str(os.getpid())],cwd=ROOT,
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=0x08000000)
        except OSError as error:print('Status panel unavailable: '+str(error),flush=True)

    def update(self,phase,session=None,error=None):
        if phase not in MESSAGES:raise ValueError('Unknown transition status')
        now=time.time_ns()
        if self.started is None or (session is not None and session!=self.session):
            self.started=now;self.session=session
        title,detail=MESSAGES[phase]
        if phase=='manual':detail=manual_mission_message(self.session)
        message={'phase':phase,'visible':True,'title':title,'detail':detail,'session':self.session,
            'started_at_ns':self.started,'updated_at_ns':now,'error':error,
            'busy':phase not in ('loaded','done','error','manual','game_unavailable','rejected')}
        if error:message['user_error']=friendly_error(error)
        if error and 'tactical transition is already active' in str(error).lower():message['action']='cancel_unfinished'
        if phase in ('loaded','done'):message['hide_after_ns']=now+3_000_000_000
        try:write_json(self.path,message)
        except OSError as issue:print('Status message could not be saved: '+str(issue),flush=True)
        return message


class SilentStatus:
    def update(self,*args,**kwargs):pass
