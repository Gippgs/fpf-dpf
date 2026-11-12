# FPF + DPF

Плагин для Codex и Claude Code. Подбирает и применяет паттерны First Principles Framework и предметных DPF, а в начале ответа перечисляет фактически применённые паттерны.

## Codex

В терминале:

```text
codex plugin marketplace add Gippgs/fpf-dpf
codex plugin add fpf-dpf@gippgs-plugins
```

Откройте новый чат и попросите: «Примени FPF и подходящие DPF к моей задаче».

## Claude Code

В терминале:

```text
claude plugin marketplace add Gippgs/fpf-dpf
claude plugin install fpf-dpf@gippgs-plugins
```

В сеансе Claude Code используйте `/fpf-dpf:fpf-dpf` и опишите задачу. Эти команды предназначены для Claude Code, включая локальные сеансы Claude Code Desktop.

## Требования и обновление

Для работы с корпусом нужны Python 3.10+ с SQLite FTS5 и доступ к GitHub. В Codex на Windows может использоваться комплектный Python. В Claude Code установите Python, если интерпретатор ещё не доступен.

Навык проверяет версию публикаций [ailev/FPF](https://github.com/ailev/FPF) в начале каждой новой задачи. При изменениях он загружает публичный корпус и сохраняет проверенный снимок локально. В запросы к GitHub не включаются материалы задачи. Корпус, индексы и персональные настройки не входят в репозиторий. Для работы без сети нужен ранее загруженный снимок.

Обновления кода плагина распространяются через каталог вашего клиента. [Codex](https://developers.openai.com/plugins/build/plugins) · [Claude Code](https://code.claude.com/docs/en/plugin-marketplaces)

У обоих каталогов общая папка `plugins/fpf-dpf` с двумя манифестами и общим навыком. Сведения об авторах и условиях использования исходных материалов приведены в [NOTICE](plugins/fpf-dpf/NOTICE.md).
