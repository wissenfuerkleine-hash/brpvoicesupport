require('dotenv').config();
const { client } = require('./bot');

if (!process.env.DISCORD_TOKEN) {
  console.error('[Main] DISCORD_TOKEN is not set. Please add it as a secret.');
  process.exit(1);
}
if (!process.env.CLIENT_ID) {
  console.error('[Main] CLIENT_ID is not set. Please add it as a secret.');
  process.exit(1);
}

client.login(process.env.DISCORD_TOKEN).catch(err => {
  console.error('[Main] Login failed:', err.message);
  process.exit(1);
});
