# The Crew Motorfest — Settings Tweaker

Внешний твикер настроек для **The Crew Motorfest (PC, Steam / Ubisoft Connect)**:
даёт выключить и поменять то, чего нет в игровом меню, правкой файлов конфигурации.

## Безопасность

В игре стоит античит **BattlEye**. Поэтому твикер **не** внедряет DLL, не патчит exe
и не пишет в память игры. Он правит только XML-файлы в папке

```
%USERPROFILE%\Documents\TheCrewMotorfest\*.xml
```

(папка «Документы», перенесённая в OneDrive или на другой диск, находится автоматически).
Перед каждой записью создаётся резервная копия в `TheCrewMotorfest\_tweaker_backups\`.
Файлы привязок `Bindings_*.xml` по умолчанию не трогаются.

## Установка

1. Установите [Python 3](https://www.python.org/downloads/) с галочкой *Add python.exe to PATH*.
2. Скопируйте папку `TheCrewMotorfest` из репозитория в любое место.
3. **Закройте игру** и запустите `Motorfest_Tweaker.bat`.

## Что умеет

| Пункт меню | Пресет | Что делает |
|---|---|---|
| 2 | `clean_image` | Выключает motion blur, хроматическую аберрацию, зерно, виньетку, DOF, искажения линз и тряску камеры |
| 3 | `fps_unlock` | Выключает V-Sync и убирает лимит FPS (ограничивайте FPS через драйвер NVIDIA/AMD) |
| 4 | `fov_max` | Ставит максимальный FOV, если такой параметр есть в конфиге |
| 6 / 7 | `lock` / `unlock` | Делает конфиги «только для чтения», чтобы игра не сбрасывала их при запуске |
| 8 | `restore` | Откат последних изменений |

Пресеты подбирают параметры по имени: `MotionBlur`, `ChromaticAberration`, `FieldOfView`
и т. д. Значение записывается в том же формате, что уже стоит в файле
(`true/false`, `1/0`, `On/Off`, число с тем же числом знаков после запятой).
Если параметра нет, твикер так и напишет: «Не найдено в конфиге».

## Если что-то не нашлось

Имена параметров в конфиге Motorfest публично не задокументированы и могут
меняться с патчами. Порядок такой:

1. Пункт **1 (scan)** выведет все параметры и сохранит их в `settings_dump.txt`.
2. Найдите нужный параметр и задайте его вручную:
   ```
   py motorfest_tweaker.py set MotionBlur=off FieldOfView=1.0
   ```
3. Или добавьте правило в `presets\*.json` (формат см. в файлах пресетов) и
   пришлите `settings_dump.txt` в issue, чтобы пресеты можно было обновить.

## Командная строка

```
py motorfest_tweaker.py scan [слова-фильтр] [--out файл]
py motorfest_tweaker.py apply clean_image fps_unlock [--dry-run] [--lock]
py motorfest_tweaker.py set KEY=VALUE ... [--dry-run]
py motorfest_tweaker.py restore | lock | unlock | presets
py motorfest_tweaker.py --dir "D:\путь\к\TheCrewMotorfest" scan
```

## Тесты

```
python -m unittest discover -s tests -v
```
