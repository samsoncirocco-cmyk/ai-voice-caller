/**
 * Jest configuration for Cloud Function unit tests
 */
module.exports = {
  testEnvironment: 'node',
  testMatch: ['**/tests/unit/**/*.js'],
  collectCoverageFrom: [
    'cloud-functions/**/index.js',
    '!**/node_modules/**'
  ],
  coverageDirectory: 'coverage',
  coverageReporters: ['text', 'lcov', 'html'],
  verbose: true,
  testTimeout: 30000,
  
  // Mock cloud dependencies
  moduleNameMapper: {
    '@google-cloud/vertexai': '<rootDir>/tests/mocks/vertexai.js',
    '@google-cloud/firestore': '<rootDir>/tests/mocks/firestore.js',
    '@google-cloud/secret-manager': '<rootDir>/tests/mocks/secret-manager.js'
  }
};
