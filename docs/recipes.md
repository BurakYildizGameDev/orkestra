# Recipes: running the night queue on a schedule

Orkestra does not install a service. `orkestra queue run` is an ordinary command: it works
through the queue and exits. To start it every night, let the system scheduler run it.

> **Sleep stops the queue.** A computer that sleeps or hibernates runs nothing. Keep it awake
> at night, or let the scheduler wake it (Windows: "Wake the computer to run this task").
> A run that was cut off is not lost: items left `running` go back to `pending` the next time
> `queue run` starts.

## During the day

```bash
cd ~/projects/my-app
orkestra queue add tasks/docstrings.yaml                 # checked now, runs later
orkestra queue add tasks/tests-batch.yaml --profile cheap
orkestra queue list
```

Each item remembers the folder it was added from. When it runs, relative paths and the
project's `orkestra.yaml` are read from there, so the scheduler may start `queue run` in any
folder. Without `--profile`, an item runs on `queue.default_profile` (`cheap` by default).

## The command to schedule

```bash
orkestra queue run --until 07:00 --notify
```

- `--until 07:00`: no new item starts after 07:00; the one running finishes.
- `--max-cost-usd 0.50`: no new item starts once 0.50 USD is spent, and an item estimated to
  go over what is left is skipped. `--max-cost-usd 0` runs free work only. Without the flag, a
  batch that would ask for cost confirmation is skipped (nobody is there to answer) and stays
  in the queue; a single task never asks, as with `orkestra run`.
- `--notify`: one notification at the end with the counts only ("5 finished, 1 failed").
- Only one `queue run` works at a time; a second one exits with code 5. A lock left behind by
  a crashed run is cleared automatically.

In the morning: `orkestra status`, then `orkestra review` and `orkestra apply`.

## Notifications

```yaml
notify:
  desktop: true                      # needs the extra: uv tool install "orkestra-cli[notify]"
  ntfy_topic_env: ORKESTRA_NTFY_TOPIC
```

Phone notifications go through [ntfy](https://ntfy.sh): install the app, subscribe to a topic
with a long, hard to guess name, and put that name in the variable named by `ntfy_topic_env`
(not in the config file). Anyone who knows the topic can read it, which is why a notification
never holds task text, code or file names. Try it with `orkestra notify test`.

## Linux and macOS: cron

Find the full path first, because cron starts with a short `PATH`:

```bash
command -v orkestra          # for example /home/you/.local/bin/orkestra
crontab -e
```

```cron
# every night at 23:00; stop starting new work at 07:00
0 23 * * * ORKESTRA_NTFY_TOPIC=your-long-topic /home/you/.local/bin/orkestra queue run --until 07:00 --notify >> /home/you/.orkestra/queue.log 2>&1
```

Desktop notifications from cron usually do not show (cron has no desktop session); use ntfy
there. On macOS, launchd works the same way; cron is enough for most setups.

## Windows: Task Scheduler

Find the full path in PowerShell:

```powershell
(Get-Command orkestra).Source    # for example C:\Users\you\.local\bin\orkestra.exe
setx ORKESTRA_NTFY_TOPIC "your-long-topic"   # optional, for phone notifications
```

Create the task (every day at 23:00):

```powershell
schtasks /Create /SC DAILY /ST 23:00 /TN "Orkestra queue" /TR "\"C:\Users\you\.local\bin\orkestra.exe\" queue run --until 07:00 --notify"
```

Or with PowerShell, with "wake to run":

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\Users\you\.local\bin\orkestra.exe" -Argument "queue run --until 07:00 --notify"
$trigger = New-ScheduledTaskTrigger -Daily -At 23:00
$options = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable
Register-ScheduledTask -TaskName "Orkestra queue" -Action $action -Trigger $trigger -Settings $options
```

Desktop notifications show only when the task runs as you while you are signed in ("Run only
when user is logged on"). Check the result with `orkestra queue list` or in Task Scheduler's
history.
