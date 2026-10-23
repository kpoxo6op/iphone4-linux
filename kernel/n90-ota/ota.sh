#!/bin/sh
# n90-ota: the phone updates its own software, without the laptop.
#
#   n90-ota check    fetch the latest release; install it if it is newer than
#                    what runs, signed and complete, and put the old software
#                    back if the phone is not healthy with it a minute later
#   n90-ota serve    what keep runs: check five minutes after it starts, then
#                    every six hours (every half hour while nothing answers)
#   n90-ota status
#
# A release (harness/phone_release.py) is three files on the repository's
# GitHub Releases: phone-release.manifest (version, the git commit and its
# time, then the SHA-256 and mode of every file), its Ed25519 signature
# (n90-sig, key in /etc/n90/ota.pub) and phone-release.tar. Nothing is
# installed unless the signature is good and every file matches its hash, so
# the download itself need not be trusted. Scenes are not part of a release;
# the phone keeps the ones it shows.
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
BASE=${N90_OTA_URL:-https://github.com/kpoxo6op/iphone4-linux/releases/latest/download}
KEY=/etc/n90/ota.pub
WORK=/run/ota
STATE=/opt/n90-ota	# what runs: version, commit time; backup of the last update

mkdir -p "$WORK" "$STATE"
say() { echo "$(date '+%F %T') $*" >> "$WORK/ota.log"; }
journal() { echo "{\"t\":$(date +%s),\"e\":\"ota\",\"state\":\"$1\",\"version\":\"$2\"}" >> /run/soy/journal.jsonl; }
field() { sed -n "s/^$1 //p" "$WORK/new/phone-release.manifest" | head -1; }

# Busybox's own wget has no TLS; /opt/n90-ota/wget is a busybox built with it
# (kernel/n90-ota/Makefile). It does not check certificates, which is why
# nothing counts until the signature does.
fetch() {
	/opt/n90-ota/wget -q -T 30 -O "$WORK/new/$1.part" "$BASE/$1" 2>> "$WORK/wget.log" &&
		mv "$WORK/new/$1.part" "$WORK/new/$1"
}

healthy() {
	for p in n90-keep soy n90-battery n90-wifi-keep; do
		[ -n "$(pidof $p)" ] || { echo "$p is not running"; return 1; }
	done
	pid=$(cat /run/soy/renderer.pid 2>/dev/null)
	case "$(readlink /proc/$pid/exe)" in "/opt/soy/$1/soy") ;; *)
		echo "the renderer is not the new one"; return 1 ;; esac
	grep -q '"bundle_loads":[1-9]' /run/soy/status.json || { echo "the renderer loaded no scenes"; return 1; }
	[ "$firewall_was" != On ] || [ "$(cat /run/net/firewall 2>/dev/null)" = On ] ||
		{ echo "the firewall is off"; return 1; }
	/usr/sbin/n90-ota status > /dev/null || { echo "the new updater does not run"; return 1; }
}

# The release's Soy beside the current one, with the scenes the phone shows.
stage_soy() {
	new=$WORK/new/files cur=$(readlink /opt/soy/current) rel=releases/ota-$2
	cd /opt/soy || return 1
	rm -rf "$rel" && mkdir -p "$rel/assets" "$rel/scenes" || return 1
	# RAM is the disk: share what did not change with the current release.
	for f in "$new/soy/soy" "$new"/soy/assets/*; do
		name=${f#$new/soy/} old=$cur/$name
		if [ -e "$old" ] && [ "$(sha256sum < "$f")" = "$(sha256sum < "$old")" ]; then
			ln "$old" "$rel/$name"
		else
			cp "$f" "$rel/$name"
		fi || return 1
	done
	chmod 700 "$rel/soy"
	for f in "$cur"/scenes/*; do ln "$f" "$rel/scenes/"; done
	scenes=$(sed -n 's/^  "scenes_revision": "\([^"]*\)".*/\1/p' "$cur/manifest.json")
	{
		printf '{\n  "git_revision": "%s",\n  "uncommitted_soy": false,\n' "$1"
		printf '  "binary_sha256": "%s",\n  "files": {\n' "$(sha256sum "$rel/soy" | cut -d' ' -f1)"
		sep=
		for f in "$rel"/assets/* "$rel"/scenes/*; do
			printf '%s    "%s": "%s"' "$sep" "${f#$rel/}" "$(sha256sum "$f" | cut -d' ' -f1)"
			sep=',
'
		done
		printf '\n  },\n  "scenes_revision": "%s"\n}\n' "$scenes"
	} > "$rel/manifest.json"
	(cd "$rel" && sha256sum soy assets/* scenes/* manifest.json > SHA256SUMS &&
		./soy --check --assets assets --scenes scenes > /dev/null)
}

switch_soy() {
	cd /opt/soy || return 1
	cur=$(readlink current)
	[ "$cur" = "$1" ] && return 0
	ln -sfn "$1" current.new && mv -Tf current.new current
	ln -sfn "$cur" previous.new && mv -Tf previous.new previous
	kill "$(cat /run/soy/renderer.pid)" 2>/dev/null	# keep starts the new one
}

install_files() {
	rm -rf "$STATE/backup" && mkdir -p "$STATE/backup"
	readlink /opt/soy/current > "$STATE/backup/soy-release"
	: > "$STATE/backup/installed"
	grep '^file ' "$WORK/new/phone-release.manifest" | while read -r _ path sha mode; do
		case "$path" in
		sbin/*) target=/usr/sbin/${path#sbin/} ;;
		etc/*) target=/etc/${path#etc/} ;;
		opt/*) target=/opt/${path#opt/} ;;
		*) continue ;;
		esac
		saved=$(echo "$path" | tr / _)
		[ -e "$target" ] && cp -p "$target" "$STATE/backup/$saved"
		echo "$target $saved" >> "$STATE/backup/installed"
		mkdir -p "${target%/*}"
		cp "$WORK/new/files/$path" "$target.new" && chmod "$mode" "$target.new" &&
			mv "$target.new" "$target" || exit 1
	done
}

restart_services() {
	# keep and init start them again from the new files; n90-ota stays: the
	# health check is its job, and keep restarts it when it exits.
	killall n90-wifi-keep n90-battery n90-time n90-blackbox 2>/dev/null
	killall n90-keep 2>/dev/null
	[ -x /usr/sbin/n90-firewall ] && n90-firewall load > /dev/null 2>&1
}

roll_back() {
	say "rolling back: $1"
	while read -r target saved; do
		if [ -e "$STATE/backup/$saved" ]; then
			cp -p "$STATE/backup/$saved" "$target.new" && mv "$target.new" "$target"
		else
			rm -f "$target"
		fi
	done < "$STATE/backup/installed"
	switch_soy "$(cat "$STATE/backup/soy-release")"
	restart_services
	rm -rf "/opt/soy/releases/ota-$2"
	# Not again: the next check skips this release.
	echo "$2" >> "$STATE/refused"
	journal rolled-back "$2"
}

# Keep the current and previous renderer releases only.
prune() {
	cd /opt/soy/releases || return
	keep1=$(readlink /opt/soy/current) keep2=$(readlink /opt/soy/previous)
	for r in *; do
		[ "releases/$r" = "$keep1" ] || [ "releases/$r" = "$keep2" ] || rm -rf "$r"
	done
}

check() {
	rm -rf "$WORK/new" && mkdir -p "$WORK/new"
	fetch phone-release.manifest && fetch phone-release.manifest.sig ||
		{ say "no answer from $BASE"; return 3; }
	n90-sig verify "$KEY" "$WORK/new/phone-release.manifest" 2>> "$WORK/ota.log" ||
		{ say "refused: bad signature"; return 1; }
	version=$(field version) commit=$(field commit) when=$(field committed)
	case "$version" in ''|*[!A-Za-z0-9._-]*) say "refused: bad version"; return 1 ;; esac
	case "$when" in ''|*[!0-9]*) say "refused: bad commit time"; return 1 ;; esac
	if grep -qx "$version" "$STATE/refused" 2>/dev/null; then
		say "skipping $version: it was rolled back here"
		return 0
	fi
	have=$(cat "$STATE/committed" 2>/dev/null || echo 0)
	if [ "$when" -le "$have" ]; then
		say "up to date ($(cat "$STATE/version" 2>/dev/null))"
		return 0
	fi
	say "found $version"
	fetch phone-release.tar || { say "download failed"; return 3; }
	[ "$(sha256sum "$WORK/new/phone-release.tar" | cut -d' ' -f1)" = "$(field tar)" ] ||
		{ say "refused: the tar does not match"; return 1; }
	mkdir "$WORK/new/files" && tar -xf "$WORK/new/phone-release.tar" -C "$WORK/new/files" ||
		{ say "refused: cannot unpack"; return 1; }
	grep '^file ' "$WORK/new/phone-release.manifest" | while read -r _ path sha mode; do
		case "$path" in *..*|/*) echo "bad path $path"; exit 1 ;; esac
		[ "$(sha256sum "$WORK/new/files/$path" | cut -d' ' -f1)" = "$sha" ] ||
			{ echo "$path does not match"; exit 1; }
	done > "$WORK/verify.log" || { say "refused: $(cat "$WORK/verify.log")"; return 1; }
	stage_soy "$commit" "$version" || { say "refused: the renderer rejected it"; return 1; }
	firewall_was=$(cat /run/net/firewall 2>/dev/null)
	install_files || { roll_back "files did not install" "$version"; return 1; }
	switch_soy "releases/ota-$version"
	restart_services
	sleep 60
	if why=$(healthy "releases/ota-$version"); then
		echo "$version" > "$STATE/version"
		echo "$when" > "$STATE/committed"
		prune
		say "installed $version"
		journal installed "$version"
	else
		roll_back "$why" "$version"
		return 1
	fi
}

case "$1" in
check)
	check ;;
serve)
	sleep 300
	while :; do
		check
		case $? in 3) sleep 1800 ;; *) sleep 21600 ;; esac
	done ;;
status)
	echo "version $(cat "$STATE/version" 2>/dev/null || echo unknown)"
	tail -3 "$WORK/ota.log" 2>/dev/null
	true ;;
*)
	echo "usage: n90-ota check|serve|status" >&2
	exit 2 ;;
esac
