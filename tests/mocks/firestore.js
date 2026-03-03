/**
 * Mock for @google-cloud/firestore
 */

const mockData = new Map();

class MockDocumentReference {
  constructor(id, collectionId) {
    this.id = id;
    this.collectionId = collectionId;
  }
  
  async get() {
    const key = `${this.collectionId}/${this.id}`;
    const data = mockData.get(key);
    return {
      exists: !!data,
      id: this.id,
      data: () => data
    };
  }
  
  async set(data, options = {}) {
    const key = `${this.collectionId}/${this.id}`;
    if (options.merge && mockData.has(key)) {
      const existing = mockData.get(key);
      mockData.set(key, { ...existing, ...data });
    } else {
      mockData.set(key, data);
    }
    return { writeTime: new Date() };
  }
  
  async update(data) {
    const key = `${this.collectionId}/${this.id}`;
    const existing = mockData.get(key) || {};
    mockData.set(key, { ...existing, ...data });
    return { writeTime: new Date() };
  }
}

class MockQuery {
  constructor(collectionId) {
    this.collectionId = collectionId;
    this.filters = [];
    this.limitValue = 100;
    this.orderField = null;
    this.orderDirection = 'asc';
  }
  
  where(field, op, value) {
    this.filters.push({ field, op, value });
    return this;
  }
  
  orderBy(field, direction) {
    this.orderField = field;
    this.orderDirection = direction;
    return this;
  }
  
  limit(n) {
    this.limitValue = n;
    return this;
  }
  
  async get() {
    const docs = [];
    for (const [key, value] of mockData.entries()) {
      if (key.startsWith(this.collectionId + '/')) {
        docs.push({
          id: key.split('/')[1],
          exists: true,
          data: () => value
        });
      }
    }
    return { docs: docs.slice(0, this.limitValue), size: docs.length };
  }
  
  stream() {
    const results = [];
    for (const [key, value] of mockData.entries()) {
      if (key.startsWith(this.collectionId + '/')) {
        results.push({
          id: key.split('/')[1],
          data: () => value
        });
      }
    }
    return results;
  }
}

class MockCollectionReference {
  constructor(id) {
    this.id = id;
  }
  
  doc(docId) {
    return new MockDocumentReference(docId, this.id);
  }
  
  async add(data) {
    const id = `auto_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const key = `${this.id}/${id}`;
    mockData.set(key, { ...data, id });
    return new MockDocumentReference(id, this.id);
  }
  
  where(field, op, value) {
    const query = new MockQuery(this.id);
    return query.where(field, op, value);
  }
  
  orderBy(field, direction) {
    const query = new MockQuery(this.id);
    return query.orderBy(field, direction);
  }
  
  limit(n) {
    const query = new MockQuery(this.id);
    return query.limit(n);
  }
}

class Firestore {
  constructor(options = {}) {
    this.projectId = options.projectId;
  }
  
  collection(collectionId) {
    return new MockCollectionReference(collectionId);
  }
  
  static get Timestamp() {
    return {
      now: () => ({
        toDate: () => new Date(),
        toMillis: () => Date.now()
      }),
      fromDate: (date) => ({
        toDate: () => date,
        toMillis: () => date.getTime()
      })
    };
  }
  
  static get FieldValue() {
    return {
      arrayUnion: (...items) => ({ _type: 'arrayUnion', items }),
      arrayRemove: (...items) => ({ _type: 'arrayRemove', items }),
      increment: (n) => ({ _type: 'increment', n }),
      serverTimestamp: () => new Date()
    };
  }
}

// Static methods on Firestore class
Firestore.Timestamp = Firestore.Timestamp;
Firestore.FieldValue = Firestore.FieldValue;

// Helper to clear mock data between tests
function clearMockData() {
  mockData.clear();
}

module.exports = { Firestore, clearMockData };
