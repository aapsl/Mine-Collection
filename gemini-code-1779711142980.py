import os

# Файлы или папки, которые нужно проигнорировать (чтобы не раздувать архив)
EXCLUDE = {'.git', '.venv', 'venv', '__pycache__', '.env', 'mod_updater.log'}

with open('compiled_project.txt', 'w', encoding='utf-8') as outfile:
    for root, dirs, files in os.walk('.'):
        # Фильтруем папки
        dirs[:] = [d for d in dirs if d not in EXCLUDE]
        
        for file in files:
            if file.endswith('.py') and file != 'merge_code.py':
                full_path = os.path.join(root, file)
                outfile.write(f"\n\n{'='*40}\nФАЙЛ: {full_path}\n{'='*40}\n\n")
                try:
                    with open(full_path, 'r', encoding='utf-8') as infile:
                        outfile.write(infile.read())
                except Exception as e:
                    outfile.write(f"# Не удалось прочитать файл: {e}\n")

print("Готово! Отправьте мне файл compiled_project.txt")