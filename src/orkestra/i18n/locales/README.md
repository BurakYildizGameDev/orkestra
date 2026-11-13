# Translations

`en.yaml` is the source; `tr`, `de`, `es` and `fr` follow it key by key. Tests check that every
catalog has the same keys and the same `{placeholders}` as English, that no value is empty, and
that a catalog is really translated (not a copy of the English text).

Never translate: keys, `{placeholders}`, command names and flags (`orkestra init --plain`),
file and folder names (`.orkestra/HANDOFF.md`), environment variables (`ORKESTRA_CHIEF`),
config keys (`daily_usd`, `prompt_mode`), JSON fields, provider names (`ollama`, `codex`, `agy`),
and the words `Orkestra`, `git`, `worktree`, `diff`, `commit`, `branch`.

Keep the tone of the English text: short, plain sentences; address the user informally where the
language allows it (`du`, `tú`, `tu`), as the Turkish catalog does (`sen`).

## Glossary

| English | Türkçe | Deutsch | Español | Français |
|---|---|---|---|---|
| provider | sağlayıcı | Anbieter | proveedor | fournisseur |
| model | model | Modell | modelo | modèle |
| tier | kademe | Stufe | nivel | niveau |
| profile | profil | Profil | perfil | profil |
| budget | bütçe | Budget | presupuesto | budget |
| limit | sınır | Limit | límite | limite |
| consent | onay | Zustimmung | consentimiento | consentement |
| chief | şef | Chef | jefe | chef |
| worker | işçi | Worker | trabajador | travailleur |
| task | görev | Aufgabe | tarea | tâche |
| run (noun) | koşu | Lauf | ejecución | exécution |
| verifier | doğrulayıcı | Prüfer | verificador | vérificateur |
| batch | batch | Batch | lote | lot |
| handoff | devir | Übergabe | traspaso | passation |
| handoff file | devir dosyası | Übergabedatei | archivo de traspaso | fichier de passation |
| brief | özet | Kurzfassung | resumen | résumé |
| envelope | zarf | Umschlag | sobre | enveloppe |
| circuit breaker | devre kesici | Schutzschalter | cortacircuitos | disjoncteur |
| setup wizard | kurulum sihirbazı | Einrichtungsassistent | asistente de configuración | assistant de configuration |
| dry run | deneme (`--dry-run`) | Probelauf | simulación | simulation |
| cache | önbellek | Cache | caché | cache |
| secret | gizli bilgi | Geheimnis | secreto | secret |
