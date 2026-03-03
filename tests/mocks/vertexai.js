/**
 * Mock for @google-cloud/vertexai
 */

class MockGenerativeModel {
  async generateContent(prompt) {
    return {
      response: {
        candidates: [{
          content: {
            parts: [{
              text: "This is a mock response for testing purposes. Sounds like you're interested in learning more!"
            }]
          }
        }]
      }
    };
  }
}

class VertexAI {
  constructor(options) {
    this.project = options.project;
    this.location = options.location;
  }
  
  getGenerativeModel(options) {
    return new MockGenerativeModel();
  }
  
  // Legacy API
  get preview() {
    return {
      getGenerativeModel: (options) => new MockGenerativeModel()
    };
  }
}

module.exports = { VertexAI };
