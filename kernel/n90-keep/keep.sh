#!/bin/sh
# keep: restart the phone's own services when one stops, without the laptop.
#
# Busybox init respawns this script (an inittab entry added at boot), so it
# survives too. Every 2 s it checks Soy, the touch driver, the battery
# reader, the Wi-Fi keeper and the watchdog kicker. One that has been gone for 6 s is started
# the same way the boot starts it. Deploy tools that stop a service on
# purpose write an expiry time (epoch seconds) to /run/keep/hold-NAME first.
# When Soy needs a third restart within two minutes, the release before the
# current one becomes current again.
#
# keep also takes over from the kernel's panic_on_oops. An oops leaves the
# kernel damaged; rebooting at once would lose the oops message, because the
# laptop collects the kernel log over the network. keep notes the oops in the
# journal and, 30 s later, restarts the phone if it is on USB power, where
# the laptop boots it again from DFU mode. On battery a damaged phone that
# still shows pages is more use than one waiting in DFU mode.
# /run/keep/hold-oops pauses this.
#
# keep also mends the USB link. The phone's USB controller does not see the
# cable go: unplugged, it still reported a configured link, and plugged back
# into the laptop it never connected again (22 October, until a hard reset).
# When the PMU sees USB power return, or the link stays down while USB power
# is there, keep disconnects and reconnects it in software
# (/sys/class/udc/*/soft_connect): after 16 s, then 32, then about once a
# minute, as on a plain charger where no computer ever answers.
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
LOG=/run/keep/keep.log
mkdir -p /run/keep
echo 0 > /proc/sys/kernel/panic_on_oops

say() { echo "$(date '+%F %T') $*" >> "$LOG"; }
# A restart also goes in Soy's journal, which the laptop collects.
journal() { echo "{\"t\":$(date +%s),\"e\":\"restart\",\"what\":\"$1\"}" >> /run/soy/journal.jsonl; }

held() {
	[ -f "/run/keep/hold-$1" ] || return 1
	t=; read -r t 2>/dev/null < "/run/keep/hold-$1"
	case "$t" in ''|*[!0-9]*) return 1 ;; esac
	[ "$(date +%s)" -lt "$t" ]
}

# Liveness without pidof: pidof reads every /proc/PID/cmdline, which takes
# each process's mmap lock. A reader that CFS then leaves waiting behind a
# busy tailscaled blocked Soy's own memory operations for 50 ms at a time.
# /proc/PID/comm needs no mm lock, and the shell reads it without forking.
alive() {
	if [ "$1" = soy ]; then f=/run/soy/renderer.pid; else f=/run/keep/$1.pid; fi
	p=; read -r p 2>/dev/null < "$f"
	c=; [ -n "$p" ] && read -r c 2>/dev/null < "/proc/$p/comm"
	[ -n "$c" ] && [ "$c" = "$2" ] && return 0
	for d in /proc/[0-9]*; do
		c=; read -r c 2>/dev/null < "$d/comm"
		if [ "$c" = "$2" ]; then
			echo "${d#/proc/}" > "$f"
			return 0
		fi
	done
	return 1
}

start_soy() {
	cd /opt/soy || return
	now=$(date +%s)
	recent=$(awk -v now="$now" '$1 > now - 120' /run/keep/soy-starts 2>/dev/null | wc -l)
	prev=$(readlink previous)
	if [ "$recent" -ge 2 ] && [ -n "$prev" ] && [ "$prev" != "$(readlink current)" ]; then
		rm -f current.keep
		ln -s "$prev" current.keep && mv -Tf current.keep current
		: > /run/keep/soy-starts
		say "soy keeps stopping; went back to $prev"
	fi
	echo "$now" >> /run/keep/soy-starts
	scene=$(sed -n 's/.*"scene":"\([A-Za-z0-9_-]*\)".*/\1/p' /run/soy/status.json 2>/dev/null)
	arg=
	if [ -n "$scene" ] && grep -qx "$scene" current/scenes/index; then
		arg="--scene $scene"
	fi
	rm -f /run/soy/status.json
	# $arg is a checked scene ID or empty.
	# shellcheck disable=SC2086
	nohup /opt/soy/current/soy --assets /opt/soy/current/assets \
		--scenes /opt/soy/current/scenes --run /run/soy $arg \
		>/var/log/soy.log 2>&1 </dev/null &
	echo $! > /run/soy/renderer.pid
	say "started soy ($(readlink current)${scene:+, $scene})"
}

start() {
	journal "$1"
	case "$1" in
	soy) start_soy ;;
	touch)
		cd /opt/n90-touch && nohup ./n90-touch serve n90-z2.bin \
			>/run/n90-touch.log 2>&1 </dev/null &
		echo $! > /run/keep/touch.pid
		say "started touch" ;;
	battery)
		nohup /usr/sbin/n90-battery serve >/run/n90-battery.log 2>&1 </dev/null &
		echo $! > /run/keep/battery.pid
		say "started battery" ;;
	wdt)
		nohup /usr/sbin/n90-wdt 60 10 >/run/n90-wdt.log 2>&1 </dev/null &
		echo $! > /run/keep/wdt.pid
		say "started watchdog kicker" ;;
	wifi)
		nohup /usr/sbin/n90-wifi-keep >/dev/null 2>&1 </dev/null &
		echo $! > /run/keep/wifi.pid
		say "started Wi-Fi keeper" ;;
	esac
}

installed() {
	case "$1" in
	soy) [ -x /opt/soy/current/soy ] ;;
	touch) [ -x /opt/n90-touch/n90-touch ] ;;
	battery) [ -x /usr/sbin/n90-battery ] ;;
	wdt) [ -x /usr/sbin/n90-wdt ] ;;
	wifi) [ -x /usr/sbin/n90-wifi-keep ] ;;
	esac
}

# The kernel sets taint bit 7 (TAINT_DIE) on an oops.
oops_at=
check_oops() {
	t=; read -r t 2>/dev/null < /proc/sys/kernel/tainted
	case "$t" in ''|*[!0-9]*) return ;; esac
	[ $((t & 128)) -ne 0 ] || return
	now=$(date +%s)
	if [ -z "$oops_at" ]; then
		oops_at=$now
		say "kernel oops"
		echo "{\"t\":$now,\"e\":\"oops\"}" >> /run/soy/journal.jsonl
	fi
	# The oops may have taken the USB network down, so ask the PMU too.
	u=; read -r u 2>/dev/null < /run/power_supply/usb/online
	c=; read -r c 2>/dev/null < /sys/class/net/usb0/carrier
	if { [ "$u" = 1 ] || [ "$c" = 1 ]; } && [ $((now - oops_at)) -ge 30 ] &&
	    ! held oops; then
		say "restarting after the oops"
		echo b > /proc/sysrq-trigger
	fi
}

usb_reconnect() {
	for f in /sys/class/udc/*/soft_connect; do
		[ -e "$f" ] || continue
		echo disconnect > "$f"
		sleep 1
		echo connect > "$f"
	done
	say "reconnected the USB link ($1)"
}

usb_was= usb_down=0 usb_wait=16
check_usb() {
	u=; read -r u 2>/dev/null < /run/power_supply/usb/online
	st=
	for f in /sys/class/udc/*/state; do
		[ -e "$f" ] && read -r st 2>/dev/null < "$f"
	done
	if [ "$u" = 1 ] && [ "$usb_was" = 0 ]; then
		usb_reconnect "USB power came back"
		usb_down=0 usb_wait=16
	elif [ "$u" = 1 ] && [ -n "$st" ] && [ "$st" != configured ]; then
		usb_down=$((usb_down + 2))
		if [ "$usb_down" -ge "$usb_wait" ]; then
			usb_reconnect "link $st with USB power"
			usb_down=0
			[ "$usb_wait" -lt 60 ] && usb_wait=$((usb_wait * 2))
		fi
	else
		usb_down=0 usb_wait=16
	fi
	[ -n "$u" ] && usb_was=$u
}

comm_soy=soy comm_touch=n90-touch comm_battery=n90-battery comm_wdt=n90-wdt
comm_wifi=n90-wifi-keep

say "keep started"
missing_soy=0 missing_touch=0 missing_battery=0 missing_wdt=0 missing_wifi=0
while :; do
	for s in wdt soy touch battery wifi; do
		eval "m=\$missing_$s"
		eval "comm=\$comm_$s"
		if ! installed "$s" || held "$s" || alive "$s" "$comm"; then
			m=0
		else
			m=$((m + 1))
			if [ "$m" -ge 3 ]; then
				start "$s"
				m=0
			fi
		fi
		eval "missing_$s=\$m"
	done
	check_oops
	check_usb
	sleep 2
done
