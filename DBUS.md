# Praya D-Bus Commands

## Main Daemon Control

```bash
# Enable posture service
dbus-send --session --print-reply --dest=com.github.blankon.praya /com/github/blankon/Praya com.github.blankon.Praya.EnableService string:'posture'

# Disable posture service
dbus-send --session --print-reply --dest=com.github.blankon.praya /com/github/blankon/Praya com.github.blankon.Praya.DisableService string:'posture'

# List available services
dbus-send --session --print-reply --dest=com.github.blankon.praya /com/github/blankon/Praya com.github.blankon.Praya.ListServices

# Quit daemon
dbus-send --session --print-reply --dest=com.github.blankon.praya /com/github/blankon/Praya com.github.blankon.Praya.Quit
```

## Posture Service

```bash
# Get posture status
dbus-send --session --print-reply --dest=com.github.blankon.praya /com/github/blankon/Praya/Posture com.github.blankon.Praya.Posture.GetStatus

# Recalibrate
dbus-send --session --print-reply --dest=com.github.blankon.praya /com/github/blankon/Praya/Posture com.github.blankon.Praya.Posture.Recalibrate
```

## Signals

The posture service emits these D-Bus signals to `/com/github/blankon/Praya`:

- `com.github.blankon.Praya.PostureServiceStatus string:'bad'` - when slouching alert is triggered
- `com.github.blankon.Praya.PostureServiceStatus string:'good'` - when posture is restored
