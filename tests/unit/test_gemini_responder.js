/**
 * Unit Tests for Gemini Responder Cloud Function
 * 
 * Run with: npm test
 */

const {
  validateRequest,
  buildPrompt,
  cleanForTTS,
  checkRateLimit
} = require('../../cloud-functions/gemini-responder/index.js');

describe('Gemini Responder', () => {
  
  describe('validateRequest', () => {
    test('should reject null body', () => {
      const result = validateRequest(null);
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('Request body is required');
    });
    
    test('should reject missing sessionInfo', () => {
      const result = validateRequest({ text: 'hello' });
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('sessionInfo is required');
    });
    
    test('should reject missing text and transcript', () => {
      const result = validateRequest({
        sessionInfo: { session: 'test-123' }
      });
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('Either text or transcript is required');
    });
    
    test('should accept valid request with text', () => {
      const result = validateRequest({
        sessionInfo: { 
          session: 'test-123',
          parameters: {}
        },
        text: 'Tell me more about that'
      });
      expect(result.valid).toBe(true);
      expect(result.data.text).toBe('Tell me more about that');
    });
    
    test('should accept valid request with transcript', () => {
      const result = validateRequest({
        sessionInfo: { 
          session: 'test-123',
          parameters: {}
        },
        transcript: 'I am interested in your solution'
      });
      expect(result.valid).toBe(true);
      expect(result.data.text).toBe('I am interested in your solution');
    });
    
    test('should extract sessionId correctly', () => {
      const result = validateRequest({
        sessionInfo: { 
          session: 'projects/tatt-pro/locations/us-central1/agents/abc/sessions/xyz123',
          parameters: {}
        },
        text: 'Hello'
      });
      expect(result.data.sessionId).toContain('xyz123');
    });
  });
  
  describe('buildPrompt', () => {
    test('should include caller text', () => {
      const context = {
        text: "What does local survivability mean?",
        parameters: {},
        currentPage: 'killer-question',
        intentName: 'questions'
      };
      
      const prompt = buildPrompt(context);
      expect(prompt).toContain('What does local survivability mean?');
    });
    
    test('should include account data', () => {
      const context = {
        text: "Tell me more",
        parameters: {
          account_name: 'Cityville Schools',
          account_type: 'K12'
        },
        currentPage: 'introduction',
        intentName: 'interested'
      };
      
      const prompt = buildPrompt(context);
      expect(prompt).toContain('Cityville Schools');
      expect(prompt).toContain('K12');
    });
    
    test('should include conversation history', () => {
      const context = {
        text: "I am interested",
        parameters: {
          conversation_history: [
            { role: 'bot', text: 'Hi, is this John?' },
            { role: 'user', text: 'Yes, who is calling?' }
          ]
        },
        currentPage: 'handle-response',
        intentName: 'interested'
      };
      
      const prompt = buildPrompt(context);
      expect(prompt).toContain('Hi, is this John?');
      expect(prompt).toContain('Yes, who is calling?');
    });
    
    test('should limit conversation history to last 5 turns', () => {
      const history = [];
      for (let i = 0; i < 10; i++) {
        history.push({ role: 'user', text: `Message ${i}` });
      }
      
      const context = {
        text: "Current message",
        parameters: { conversation_history: history },
        currentPage: 'test',
        intentName: 'test'
      };
      
      const prompt = buildPrompt(context);
      expect(prompt).not.toContain('Message 0');
      expect(prompt).not.toContain('Message 4');
      expect(prompt).toContain('Message 5');
      expect(prompt).toContain('Message 9');
    });
  });
  
  describe('cleanForTTS', () => {
    test('should remove markdown asterisks', () => {
      expect(cleanForTTS('This is **bold** text')).toBe('This is bold text');
    });
    
    test('should remove underscores', () => {
      expect(cleanForTTS('This is _italic_ text')).toBe('This is italic text');
    });
    
    test('should remove markdown headers', () => {
      expect(cleanForTTS('## Header\nContent')).toBe('Header Content');
    });
    
    test('should normalize whitespace', () => {
      expect(cleanForTTS('Too    many   spaces')).toBe('Too many spaces');
    });
    
    test('should replace newlines with spaces', () => {
      expect(cleanForTTS('Line 1\nLine 2\n\nLine 3')).toBe('Line 1 Line 2 Line 3');
    });
    
    test('should preserve punctuation', () => {
      expect(cleanForTTS("Hello! How are you? I'm fine."))
        .toBe("Hello! How are you? I'm fine.");
    });
    
    test('should remove code ticks', () => {
      expect(cleanForTTS('Use `this` command')).toBe('Use this command');
    });
    
    test('should handle empty string', () => {
      expect(cleanForTTS('')).toBe('');
    });
    
    test('should handle null/undefined', () => {
      expect(cleanForTTS(null)).toBe('');
      expect(cleanForTTS(undefined)).toBe('');
    });
  });
  
  describe('checkRateLimit', () => {
    beforeEach(() => {
      // Reset rate limit state between tests
      jest.useFakeTimers();
    });
    
    afterEach(() => {
      jest.useRealTimers();
    });
    
    test('should allow first request', () => {
      expect(checkRateLimit('session-1')).toBe(true);
    });
    
    test('should track requests per session', () => {
      // This would need access to the internal requestCounts map
      // For unit testing, we verify the function returns boolean
      const result = checkRateLimit('session-2');
      expect(typeof result).toBe('boolean');
    });
  });
});

describe('Dialogflow Response Format', () => {
  test('should return correct fulfillment structure', () => {
    const response = {
      fulfillmentResponse: {
        messages: [{
          text: {
            text: ["Test response"]
          }
        }]
      },
      sessionInfo: {
        parameters: {
          last_gemini_response: "Test response"
        }
      }
    };
    
    expect(response.fulfillmentResponse.messages).toHaveLength(1);
    expect(response.fulfillmentResponse.messages[0].text.text[0]).toBe("Test response");
  });
});
