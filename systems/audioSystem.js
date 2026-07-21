const {
  joinVoiceChannel,
  createAudioPlayer,
  createAudioResource,
  AudioPlayerStatus,
  entersState,
  VoiceConnectionStatus,
} = require('@discordjs/voice');
const fs   = require('fs');
const path = require('path');
const config = require('../config');

let waitingConnection = null;
let waitingPlayer     = null;
let _isPlayingWaiting = false;

function audioFilePath(filename) {
  return path.join(__dirname, '..', config.AUDIO_PATH, filename);
}

function startWaiting(channel) {
  const file = audioFilePath('waiting.mp3');
  if (!fs.existsSync(file)) {
    console.log('[Audio] waiting.mp3 not found — skipping music.');
    return;
  }
  if (_isPlayingWaiting) return;

  try {
    waitingConnection = joinVoiceChannel({
      channelId:      channel.id,
      guildId:        channel.guild.id,
      adapterCreator: channel.guild.voiceAdapterCreator,
      selfDeaf:       false,
    });

    waitingPlayer = createAudioPlayer();
    waitingConnection.subscribe(waitingPlayer);

    const loop = () => {
      if (!_isPlayingWaiting) return;
      waitingPlayer.play(createAudioResource(file));
    };

    waitingPlayer.on(AudioPlayerStatus.Idle, loop);
    waitingPlayer.on('error', err => console.error('[Audio] Player error:', err.message));

    _isPlayingWaiting = true;
    loop();
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
  get isPlayingWaiting() { return _isPlayingWaiting; },
};
