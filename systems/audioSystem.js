const {
  joinVoiceChannel,
  createAudioPlayer,
  createAudioResource,
  AudioPlayerStatus,
} = require('@discordjs/voice');
const fs   = require('fs');
const path = require('path');
const config = require('../config');

let waitingConnection = null;
let waitingPlayer     = null;
let _isPlayingWaiting = false;

const AUDIO_DIR = path.join(__dirname, '..', config.AUDIO_PATH);

/** Returns a random audio file path from the /audio directory, or null if none exist. */
function pickRandom() {
  let files = [];
  try {
    files = fs.readdirSync(AUDIO_DIR).filter(f => /\.(mp3|ogg|wav|flac)$/i.test(f));
  } catch {}
  if (files.length === 0) return null;
  const file = files[Math.floor(Math.random() * files.length)];
  return path.join(AUDIO_DIR, file);
}

/** Returns a random audio file path (for DM sending). */
function getRandomFilePath() {
  return pickRandom();
}

// ── Voice-channel playback (loops random tracks) ───────────────────────────────

function startWaiting(channel) {
  if (_isPlayingWaiting) return;

  const file = pickRandom();
  if (!file) {
    console.log('[Audio] No audio files found in /audio — skipping music.');
    return;
  }

  try {
    waitingConnection = joinVoiceChannel({
      channelId:      channel.id,
      guildId:        channel.guild.id,
      adapterCreator: channel.guild.voiceAdapterCreator,
      selfDeaf:       false,
    });

    waitingPlayer = createAudioPlayer();
    waitingConnection.subscribe(waitingPlayer);

    const playNext = () => {
      if (!_isPlayingWaiting) return;
      const nextFile = pickRandom();
      if (!nextFile) return;
      waitingPlayer.play(createAudioResource(nextFile));
    };

    waitingPlayer.on(AudioPlayerStatus.Idle, playNext);
    waitingPlayer.on('error', err => {
      console.error('[Audio] Player error:', err.message);
      setTimeout(playNext, 2000); // retry after 2s on error
    });

    _isPlayingWaiting = true;
    playNext();
  } catch (err) {
    console.error('[Audio] startWaiting error:', err.message);
  }
}

function stopWaiting() {
  _isPlayingWaiting = false;
  try { waitingPlayer?.stop(true); } catch {}
  try { waitingConnection?.destroy(); } catch {}
  waitingPlayer     = null;
  waitingConnection = null;
}

module.exports = {
  startWaiting,
  stopWaiting,
  getRandomFilePath,
  get isPlayingWaiting() { return _isPlayingWaiting; },
};
