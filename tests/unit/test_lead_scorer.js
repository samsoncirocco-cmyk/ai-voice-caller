/**
 * Unit Tests for Lead Scorer Cloud Function
 * 
 * Run with: npm test
 */

const {
  validateRequest,
  getTranscriptText,
  calculateRuleScore,
  getCategory,
  getNextAction,
  SCORING_CONFIG,
  SIGNAL_PATTERNS
} = require('../../cloud-functions/lead-scorer/index.js');

describe('Lead Scorer', () => {
  
  describe('validateRequest', () => {
    test('should reject null body', () => {
      const result = validateRequest(null);
      expect(result.valid).toBe(false);
    });
    
    test('should reject missing transcript and sessionId', () => {
      const result = validateRequest({});
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('Either transcript or sessionId is required');
    });
    
    test('should accept request with transcript', () => {
      const result = validateRequest({
        transcript: [{ role: 'user', text: 'I am interested' }]
      });
      expect(result.valid).toBe(true);
    });
    
    test('should accept request with sessionId', () => {
      const result = validateRequest({
        sessionId: 'call-123'
      });
      expect(result.valid).toBe(true);
    });
  });
  
  describe('getTranscriptText', () => {
    test('should handle string transcript', () => {
      const result = getTranscriptText('This is a test');
      expect(result).toBe('This is a test');
    });
    
    test('should extract user turns from array transcript', () => {
      const transcript = [
        { role: 'bot', text: 'Hello' },
        { role: 'user', text: 'Hi there' },
        { role: 'bot', text: 'How are you?' },
        { role: 'caller', text: 'I am good' }
      ];
      
      const result = getTranscriptText(transcript);
      expect(result).toContain('Hi there');
      expect(result).toContain('I am good');
      expect(result).not.toContain('Hello');
      expect(result).not.toContain('How are you?');
    });
    
    test('should handle empty transcript', () => {
      expect(getTranscriptText([])).toBe('');
      expect(getTranscriptText('')).toBe('');
      expect(getTranscriptText(null)).toBe('');
    });
  });
  
  describe('calculateRuleScore', () => {
    test('should start with neutral score (5)', () => {
      const result = calculateRuleScore([]);
      expect(result.score).toBe(5);
    });
    
    test('should increase score for interest signals', () => {
      const transcript = [
        { role: 'user', text: 'I am interested in learning more about this' }
      ];
      
      const result = calculateRuleScore(transcript);
      expect(result.score).toBeGreaterThan(5);
      expect(result.signals.some(s => s.signal.includes('interest'))).toBe(true);
    });
    
    test('should decrease score for not interested signals', () => {
      const transcript = [
        { role: 'user', text: 'I am not interested, please stop calling' }
      ];
      
      const result = calculateRuleScore(transcript);
      expect(result.score).toBeLessThan(5);
      expect(result.signals.some(s => s.signal.includes('Not interested'))).toBe(true);
    });
    
    test('should detect timeline mentions', () => {
      const transcript = [
        { role: 'user', text: 'We are planning to upgrade next year' }
      ];
      
      const result = calculateRuleScore(transcript);
      expect(result.signals.some(s => s.signal.includes('timeline'))).toBe(true);
    });
    
    test('should detect budget discussions', () => {
      const transcript = [
        { role: 'user', text: 'What is the pricing for this solution?' }
      ];
      
      const result = calculateRuleScore(transcript);
      expect(result.signals.some(s => s.signal.includes('budget'))).toBe(true);
    });
    
    test('should detect legacy systems', () => {
      const transcript = [
        { role: 'user', text: 'We have an old PBX system from 2010' }
      ];
      
      const result = calculateRuleScore(transcript);
      expect(result.signals.some(s => s.signal.includes('legacy'))).toBe(true);
    });
    
    test('should cap score at 10', () => {
      const transcript = [
        { role: 'user', text: 'I am very interested' },
        { role: 'user', text: 'Tell me about pricing' },
        { role: 'user', text: 'We are planning changes next year' },
        { role: 'user', text: 'Our old PBX needs replacing' }
      ];
      
      const result = calculateRuleScore(transcript, {
        employeeCount: 200,
        activeRfp: true
      });
      
      expect(result.score).toBeLessThanOrEqual(10);
    });
    
    test('should floor score at 0', () => {
      const transcript = [
        { role: 'user', text: 'Not interested at all' },
        { role: 'user', text: 'We already have Cisco' },
        { role: 'user', text: 'Stop calling me' }
      ];
      
      const result = calculateRuleScore(transcript);
      expect(result.score).toBeGreaterThanOrEqual(0);
    });
    
    test('should add points for large organization', () => {
      const result = calculateRuleScore([], { employeeCount: 150 });
      expect(result.signals.some(s => s.signal.includes('Large organization'))).toBe(true);
    });
    
    test('should add points for medium organization', () => {
      const result = calculateRuleScore([], { employeeCount: 50 });
      expect(result.signals.some(s => s.signal.includes('Medium organization'))).toBe(true);
    });
    
    test('should add points for active RFP', () => {
      const result = calculateRuleScore([], { activeRfp: true });
      expect(result.signals.some(s => s.signal.includes('Active RFP'))).toBe(true);
    });
  });
  
  describe('getCategory', () => {
    test('should return hot for 9-10', () => {
      expect(getCategory(10)).toBe('hot');
      expect(getCategory(9)).toBe('hot');
    });
    
    test('should return warm for 7-8', () => {
      expect(getCategory(8)).toBe('warm');
      expect(getCategory(7)).toBe('warm');
    });
    
    test('should return qualified for 5-6', () => {
      expect(getCategory(6)).toBe('qualified');
      expect(getCategory(5)).toBe('qualified');
    });
    
    test('should return neutral for 3-4', () => {
      expect(getCategory(4)).toBe('neutral');
      expect(getCategory(3)).toBe('neutral');
    });
    
    test('should return cool for 1-2', () => {
      expect(getCategory(2)).toBe('cool');
      expect(getCategory(1)).toBe('cool');
    });
    
    test('should return cold for 0', () => {
      expect(getCategory(0)).toBe('cold');
    });
  });
  
  describe('getNextAction', () => {
    test('should recommend demo for hot leads', () => {
      const action = getNextAction(9);
      expect(action.toLowerCase()).toContain('demo');
    });
    
    test('should recommend email for warm leads', () => {
      const action = getNextAction(7);
      expect(action.toLowerCase()).toContain('email');
    });
    
    test('should recommend nurture for qualified leads', () => {
      const action = getNextAction(5);
      expect(action.toLowerCase()).toContain('nurture');
    });
    
    test('should recommend follow up later for neutral leads', () => {
      const action = getNextAction(3);
      expect(action.toLowerCase()).toContain('follow up');
    });
    
    test('should recommend DNC for cold leads', () => {
      const action = getNextAction(0);
      expect(action.toLowerCase()).toContain('do-not-call');
    });
  });
  
  describe('Signal Patterns', () => {
    test('interested patterns should match correctly', () => {
      const testCases = [
        "I'm interested",
        "Tell me more",
        "That sounds interesting",
        "I'd like to learn more"
      ];
      
      for (const text of testCases) {
        const matches = SIGNAL_PATTERNS.interested.some(p => p.test(text));
        expect(matches).toBe(true);
      }
    });
    
    test('not interested patterns should match correctly', () => {
      const testCases = [
        "Not interested",
        "No thanks",
        "Remove me from your list"
      ];
      
      for (const text of testCases) {
        const matches = SIGNAL_PATTERNS.notInterested.some(p => p.test(text));
        expect(matches).toBe(true);
      }
    });
    
    test('timeline patterns should match correctly', () => {
      const testCases = [
        "Maybe next year",
        "This quarter",
        "We're in the planning phase"
      ];
      
      for (const text of testCases) {
        const matches = SIGNAL_PATTERNS.timeline.some(p => p.test(text));
        expect(matches).toBe(true);
      }
    });
    
    test('competitor patterns should match correctly', () => {
      const testCases = [
        "We use Cisco",
        "We have Avaya",
        "Microsoft Teams handles our calls"
      ];
      
      for (const text of testCases) {
        const matches = SIGNAL_PATTERNS.competitor.some(p => p.test(text));
        expect(matches).toBe(true);
      }
    });
  });
});

describe('Scoring Configuration', () => {
  test('should have positive engagement scores', () => {
    expect(SCORING_CONFIG.engagement.multipleQuestions).toBeGreaterThan(0);
    expect(SCORING_CONFIG.engagement.mentionedTimeline).toBeGreaterThan(0);
  });
  
  test('should have positive interest scores', () => {
    expect(SCORING_CONFIG.interest.expressedInterest).toBeGreaterThan(0);
    expect(SCORING_CONFIG.interest.agreedToMeeting).toBeGreaterThan(0);
  });
  
  test('should have negative scores for objections', () => {
    expect(SCORING_CONFIG.negative.notInterested).toBeLessThan(0);
    expect(SCORING_CONFIG.negative.doNotCall).toBeLessThan(0);
  });
});
