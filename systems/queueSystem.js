const mongoose = require('mongoose');

// In-memory fallback
const memQueue = new Map(); // userId → entry

function dbReady() {
  return mongoose.connection.readyState === 1;
}

class QueueSystem {
  constructor() {
    this._io = null;
  }

  setIO(io) {
    this._io = io;
  }

  emit(event, data) {
    if (this._io) this._io.emit(event, data);
  }

  async add(member) {
    try {
      const entry = {
        userId: member.id,
        username: member.user.username,
        avatarURL: member.user.displayAvatarURL({ size: 64 }),
        guildId: member.guild.id,
        joinedAt: new Date(),
      };

      if (dbReady()) {
        const Queue = require('../models/Queue');
        await Queue.findOneAndUpdate({ userId: member.id }, entry, { upsert: true, new: true });
      } else {
        memQueue.set(member.id, entry);
      }

      const list = await this.getAll();
      this.emit('queueUpdate', list);
      return list;
    } catch (err) {
      console.error('[QueueSystem] add error:', err.message);
    }
  }

  async remove(userId) {
    try {
      if (dbReady()) {
        const Queue = require('../models/Queue');
        await Queue.deleteOne({ userId });
      } else {
        memQueue.delete(userId);
      }
      const list = await this.getAll();
      this.emit('queueUpdate', list);
      return list;
    } catch (err) {
      console.error('[QueueSystem] remove error:', err.message);
    }
  }

  async getAll() {
    if (dbReady()) {
      const Queue = require('../models/Queue');
      return Queue.find().sort({ joinedAt: 1 }).lean();
    }
    return [...memQueue.values()].sort((a, b) => a.joinedAt - b.joinedAt);
  }

  async getNext() {
    if (dbReady()) {
      const Queue = require('../models/Queue');
      return Queue.findOne().sort({ joinedAt: 1 }).lean();
    }
    const sorted = [...memQueue.values()].sort((a, b) => a.joinedAt - b.joinedAt);
    return sorted[0] || null;
  }

  async has(userId) {
    if (dbReady()) {
      const Queue = require('../models/Queue');
      return !!(await Queue.findOne({ userId }).lean());
    }
    return memQueue.has(userId);
  }

  async clear() {
    if (dbReady()) {
      const Queue = require('../models/Queue');
      await Queue.deleteMany({});
    } else {
      memQueue.clear();
    }
    this.emit('queueUpdate', []);
  }

  async count() {
    if (dbReady()) {
      const Queue = require('../models/Queue');
      return Queue.countDocuments();
    }
    return memQueue.size;
  }
}

module.exports = new QueueSystem();
