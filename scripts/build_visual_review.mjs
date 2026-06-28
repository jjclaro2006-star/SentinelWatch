import fs from 'node:fs/promises';

const input = 'data/processed/river_background_candidates.geojson';
const outCsv = 'data/processed/river_background_visual_review.csv';
const outGeoJson = 'data/processed/river_background_visual_review.geojson';

// Only clean points are promoted to the training set. These are the stable,
// completed batches reported to the user; unfinished or ambiguous points are
// deliberately not included.
const cleanIndices = [
  0,1,3,6,11,12,14,15,16,18,19,21,22,24,25,26,28,29,
  30,33,34,35,38,41,43,45,46,48,49,52,53,56,57,58,
  63,65,67,68,69,70,71,73,75,76,78,82,84,85,86,
  91,92,95,98,100,101,102,103,104,106,107,109,112,114,115,116,118,119,
  121,122,123,124,125,126,128,129,130,131,132,133,136,139,142,143,144,145,147,149,
  153,154,155,156,157,158,159,160,161,163,164,165,170,172,174,175,176,177,178,
  181,185,187,189,190,192,194,197,198,199,200,201,202,206,209,
  210,213,214,217,218,220,221,222,227,229,230,231,233,235,237,239,
  240,243,244,248,249,251,253,254,255,258,259,260,263,265,268,
  270,278,279,280,281,283,292,294,295,297,298,
  300,301,302,303,304,305,306,307,309,311,312,313,314,315,318,319,320,322,323,326,328,329,
  330,334,335,337,338,340,341,342,344,348,349,351,353,355,359,
  361,366,369,371,372,373,374,375,376,378,379,380,383,384,386,388,389,390,391,393,394,395,396,
  401,402,405,
  411,412,413,414,416,418,423,424,425,426,427,428,429,
  431,432,433,434,436,441,442,443,445,448,449,453,454,455,458,459,
  460,461,463,465,466,467,469,470,475,476,477,480,481,483,486,487,488,489,
  490,491,495,497,498,499,500,501,503,504,505,508,509,511,512,516,
  520,523,524,525,526,527,529,531,533,534,535,538,541,543,544,545,546,548,549,
  551,552,557,560,561,563,564,565,566,567,568,569,570,571,572,573,574,575,576,577,578,579,
  581,582,583,584,586,587,588,590,591,592,594,595,596,602,608,609,
  612,613,619,620,621,623,624,625,626,627,631,633,634,636,637,638,639,
  640,644,646,647,648,652,654,656,657,658,659,660,666,667,669,
  670,673,678,680,681,682,683,687,688,689,690,693,696,697,
  702,703,706,707,708,711,712,714,716,719,723,724,728,729,
  731,734,736,739,744,746,747,749,750,751,754,755,756,757,758,
  760,763,765,768,774,781,
  796,797,798,805,809,
  825,831,842,
  865,867,873,875,
  880,881,882,883,884,886,887,888,889,
  890,892,893,894,895,896,898,899,
  901,902,903,904,905,906,908,
  910,912,913,914,915,916,921,922,923,924,925,927,928,929,
  930,932,935,936,937,938,939,
  940,948,951,952,953,954,955,956,957,958,959,
  960,961,962,963,964,965,966,
  970,972,973,981,983,988,
  990,991,992,993,994,995,
  1000,1001,1002,1003,1004,1005,1006,1007,1009,
  1010,1013,1015,1016,1017,1018,1019,
  1020,1021,1022,1023,1024,1026,1027,1029,
  1031,1032,1033,1034,1038,1039,
  1042,1043,1044,1048,1049,
  1051,1053,1054,1056,1059,
  1060,1061,1062,1063,1064,1067,1068,1069,
  1070,1071,1073,1074,1075,1076,
];

const source = JSON.parse(await fs.readFile(input, 'utf8'));
const features = source.features
  .map((feature, index) => ({ feature, index }))
  .filter(({ index }) => cleanIndices.includes(index));
const csv = [
  'candidate_index,longitude,latitude,review_result,dataset_label,review_method',
  ...features.map(({ feature, index, label }) => {
    const [longitude, latitude] = feature.geometry.coordinates;
    return [index, longitude, latitude, 'limpio', 'hard_negative', 'manual_visual_google_maps_satellite'].join(',');
  }),
].join('\n') + '\n';

const geojson = {
  type: 'FeatureCollection',
  name: 'river_background_visual_review',
  features: features.map(({ feature, index }) => ({
    ...feature,
    properties: {
      ...feature.properties,
      candidate_index: index,
      review_result: 'limpio',
      dataset_label: 'hard_negative',
      review_method: 'manual_visual_google_maps_satellite',
    },
  })),
};

await fs.writeFile(outCsv, csv);
await fs.writeFile(outGeoJson, JSON.stringify(geojson, null, 2));
console.log(JSON.stringify({ hard_negatives: features.length }));
