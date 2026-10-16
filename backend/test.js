const test = require("node:test");
const assert = require("node:assert/strict");
const { SPOTS, scoreSpot } = require("./server.js");

test("spots.json defines 5 valid dial beaches", () => {
  assert.equal(SPOTS.length, 5);
  for (const s of SPOTS) {
    assert.equal(typeof s.pos, "number");
    assert.equal(typeof s.name, "string");
    assert.equal(typeof s.lat, "number");
    assert.equal(typeof s.lon, "number");
    assert.equal(typeof s.facing, "number");
  }
});

test("Surfline-calibrated LOTUS scorer rates flat onshore as POOR and solid offshore as GOOD/EPIC", () => {
  const spot = SPOTS[2]; // Curl Curl
  const smallOnshore = scoreSpot(spot, {
    swell_h: 0.3,
    swell_p: 7,
    swell_d: 95,
    wind_spd: 18,
    wind_d: 95,
    wind_wave_h: 0.4
  });
  const solidOffshore = scoreSpot(spot, {
    swell_h: 1.8,
    swell_p: 15,
    swell_d: 135,
    wind_spd: 12,
    wind_d: 275,
    wind_wave_h: 0.1
  });

  assert.ok(smallOnshore.score < 30, `Expected small onshore score < 30, got ${smallOnshore.score}`);
  assert.ok(solidOffshore.score >= 70, `Expected solid offshore score >= 70, got ${solidOffshore.score}`);
  assert.equal(solidOffshore.wind_condition, "Clean Offshore");
});
