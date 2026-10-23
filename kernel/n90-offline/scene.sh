#!/bin/sh
# n90-scene: put a scene on the screen from the phone itself.
#
#   n90-scene put FILE [--show]
#
# Without a connection nothing on the laptop can publish, so programs on the
# phone (n90-story) publish here. It is the switch the laptop's scene.py makes
# (soy/tools/scene.py, hot_publish): a new release beside the current one
# that shares its renderer and fonts, the renderer's own check of every
# scene, an atomic switch of /opt/soy/current and SIGHUP, with the previous
# release put back if the renderer rejects it.
#
# FILE is a scene with Soy's frontmatter (docs/soy/scenes.md) whose source
# starts with "phone". When the laptop next reaches the phone it copies such
# scenes into the scene library (scene.py adopt), so they survive a reboot.
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
umask 077

fail() { echo "n90-scene: $*" >&2; exit 1; }

[ "$1" = put ] && [ -f "$2" ] || fail "usage: n90-scene put FILE [--show]"
file=$2
show=$3
head -1 "$file" | grep -qx -- --- || fail "$file has no frontmatter"
id=$(sed -n '2,12s/^id: *\([A-Za-z0-9_-]\{1,40\}\) *$/\1/p' "$file" | head -1)
[ -n "$id" ] || fail "$file has no valid id"
sed -n '2,12p' "$file" | grep -q '^source: *phone' || fail "$file is not marked source: phone"
[ "$(wc -c < "$file")" -le 131072 ] || fail "$file is over 128 KiB"

cd /opt/soy || fail "no Soy install"
exec 9> /run/soy/n90-scene.lock
flock 9
cur=$(readlink current)
case "$cur" in releases/*) ;; *) fail "unexpected current release: $cur" ;; esac
stage=releases/.phone-$$
trap 'rm -rf "/opt/soy/$stage"' EXIT
mkdir -p "$stage/assets" "$stage/scenes"
ln "$cur/soy" "$stage/soy"
for f in "$cur"/assets/*; do ln "$f" "$stage/assets/"; done
for f in "$cur"/scenes/*; do
	case "${f##*/}" in index|"$id.md") ;; *) ln "$f" "$stage/scenes/" ;; esac
done
cp "$cur/scenes/index" "$stage/scenes/index"
grep -qx "$id" "$stage/scenes/index" || echo "$id" >> "$stage/scenes/index"
cp "$file" "$stage/scenes/$id.md"

cd "$stage"
field() { sed -n "s/^  \"$1\": \"*\([^\",]*\)\"*,*$/\1/p" "/opt/soy/$cur/manifest.json"; }
{
	printf '{\n  "git_revision": "%s",\n  "uncommitted_soy": %s,\n' \
		"$(field git_revision)" "$(field uncommitted_soy)"
	printf '  "binary_sha256": "%s",\n  "files": {\n' "$(field binary_sha256)"
	sep=
	for f in assets/* scenes/*; do
		printf '%s    "%s": "%s"' "$sep" "$f" "$(sha256sum "$f" | cut -d' ' -f1)"
		sep=',
'
	done
	printf '\n  },\n  "scenes_revision": "phone-%s"\n}\n' "$(date +%s)"
} > manifest.json
sha256sum soy assets/* scenes/* manifest.json > SHA256SUMS
./soy --check --assets assets --scenes scenes --scene "$id" > /dev/null ||
	fail "the renderer rejected $id"
release=releases/phone-$(sha256sum manifest.json | cut -c1-12)
cd /opt/soy
[ -e "$release" ] || mv "$stage" "$release"

before=$(sed -n 's/.*"bundle_loads":\([0-9]*\).*/\1/p' /run/soy/status.json)
failures=$(sed -n 's/.*"bundle_failures":\([0-9]*\).*/\1/p' /run/soy/status.json)
ln -sfn "$release" current.new && mv -Tf current.new current
ln -sfn "$cur" previous.new && mv -Tf previous.new previous
p=$(cat /run/soy/renderer.pid)
case "$(readlink "/proc/$p/exe")" in /opt/soy/releases/*/soy) ;; *) fail "unexpected renderer" ;; esac
kill -HUP "$p"
n=0
while [ $n -lt 75 ]; do
	sleep 0.2
	now=$(sed -n 's/.*"bundle_loads":\([0-9]*\).*/\1/p' /run/soy/status.json)
	bad=$(sed -n 's/.*"bundle_failures":\([0-9]*\).*/\1/p' /run/soy/status.json)
	if [ -n "$bad" ] && [ "$bad" != "$failures" ]; then
		ln -sfn "$cur" current.new && mv -Tf current.new current
		kill -HUP "$p"
		fail "the renderer did not take $id; the previous scenes are back"
	fi
	[ -n "$now" ] && [ "$now" != "$before" ] && break
	n=$((n + 1))
done
echo "{\"t\":$(date +%s),\"e\":\"wrote\",\"scene\":\"$id\"}" >> /run/soy/journal.jsonl
[ "$show" = --show ] && printf 'goto %s\n' "$id" 1<> /run/soy/control
echo "published $id ($release)"
