# Задание

## Цель
Создать виртуальное окружение для Python и установить в него Django.

## Шаги выполнения

### 1. Создание виртуального окружения

#### Windows (PowerShell):
```powershell
python -m venv venv
```

#### Windows (Command Prompt):
```cmd
python -m venv venv
```

#### Linux/Mac:
```bash
python3 -m venv venv
```

### 2. Активация виртуального окружения

#### Windows (PowerShell):
```powershell
.\venv\Scripts\Activate.ps1
```

Если возникает ошибка выполнения скриптов, выполните:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

#### Windows (Command Prompt):
```cmd
venv\Scripts\activate.bat
```

#### Linux/Mac:
```bash
source venv/bin/activate
```

После активации в начале строки терминала должно появиться `(venv)`.

### 3. Установка Django

После активации виртуального окружения выполните:

```bash
pip install django
```

Или для установки конкретной версии:

```bash
pip install django==4.2.0
```

### 4. Проверка установки

Проверьте, что Django установлен корректно:

```bash
python -m django --version
```

Или:

```bash
django-admin --version
```

### 5. Деактивация виртуального окружения

Когда работа с виртуальным окружением завершена, выполните:

```bash
deactivate
```

## Дополнительные рекомендации

- Рекомендуется создать файл `requirements.txt` для отслеживания зависимостей:
  ```bash
  pip freeze > requirements.txt
  ```

- Для установки зависимостей из файла `requirements.txt`:
  ```bash
  pip install -r requirements.txt
  ```

### 6. Создание Django проекта

После установки Django создайте новый проект:

#### Windows (PowerShell):
```powershell
.\venv\Scripts\Activate.ps1
django-admin startproject socworker_project .
```

#### Windows (Command Prompt):
```cmd
venv\Scripts\activate.bat
django-admin startproject socworker_project .
```

#### Linux/Mac:
```bash
source venv/bin/activate
django-admin startproject socworker_project .
```

**Примечание:** Точка в конце команды означает, что проект будет создан в текущей директории.

### 7. Запуск локального сервера разработки

После создания проекта запустите сервер разработки:

#### Windows (PowerShell):
```powershell
.\venv\Scripts\Activate.ps1
python manage.py runserver
```

#### Windows (Command Prompt):
```cmd
venv\Scripts\activate.bat
python manage.py runserver
```

#### Linux/Mac:
```bash
source venv/bin/activate
python manage.py runserver
```

После запуска сервер будет доступен по адресу: **http://127.0.0.1:8000/** или **http://localhost:8000/**

Для остановки сервера нажмите `Ctrl+C` в терминале.

## Статус выполнения

✅ Виртуальное окружение создано  
✅ Django установлен (версия 4.2.28)  
✅ Django проект создан (`socworker_project`)  
✅ Файл `requirements.txt` создан  
✅ Локальный сервер запущен и работает на http://127.0.0.1:8000/

## Примечания

- Убедитесь, что Python установлен на вашей системе (версия 3.8 или выше)
- Виртуальное окружение позволяет изолировать зависимости проекта от глобальной установки Python
- Папка `venv` должна быть добавлена в `.gitignore`, чтобы не попадать в систему контроля версий
- Для проверки работы сервера откройте браузер и перейдите по адресу http://127.0.0.1:8000/
