-- Sandbox test data — 5 fake Smith Mountain Lake striper trips.
-- Created 2026-08-30. Run ONLY against fishing-log-sandbox.
--
-- Every trip is labelled "SANDBOX TEST DATA" in its notes so it is obvious at a
-- glance that none of this is real. If you ever see one of these in the live
-- app, something is pointed at the wrong database.
--
-- Safe to re-run: it clears its own rows first (matched on the label), so you
-- get 5 trips rather than 10. It only ever touches rows it created.

begin;

-- Children go first — they reference sessions(id).
delete from fish  where session_id in (select id from sessions where notes like 'SANDBOX TEST DATA%');
delete from spots where session_id in (select id from sessions where notes like 'SANDBOX TEST DATA%');
delete from sessions where notes like 'SANDBOX TEST DATA%';

insert into sessions
  (user_email, date, start_time, end_time, hours_fished, location_name,
   latitude, longitude, weather, air_temp, water_temp, bait_lure,
   fishing_style, num_anglers, dwr_filed, notes, moon_phase)
values
  ('jcal0064@gmail.com', '2026-05-14', '06:00', '10:30', 4.5, 'Hales Ford Bridge',
   37.0912, -79.6423, 'Partly Cloudy', 68, 64, 'Gizzard Shad',
   'Trolling', 2, 0, 'SANDBOX TEST DATA #1 - good morning bite off the points', 'Waxing Crescent'),

  ('jcal0064@gmail.com', '2026-06-02', '05:30', '11:00', 5.5, 'Blackwater Arm',
   37.0488, -79.5761, 'Clear', 74, 71, 'Bucktail Jig',
   'Trolling', 1, 0, 'SANDBOX TEST DATA #2 - slow, fish held deep', 'Full Moon'),

  ('jcal0064@gmail.com', '2026-06-21', '17:00', '21:00', 4.0, 'Craddock Creek',
   37.1024, -79.6688, 'Overcast', 81, 78, 'Live Shad',
   'Live Bait', 3, 1, 'SANDBOX TEST DATA #3 - evening topwater blowups', 'Waning Gibbous'),

  ('jcal0064@gmail.com', '2026-07-08', '06:15', '09:45', 3.5, 'Hales Ford Bridge',
   37.0912, -79.6423, 'Rain', 72, 80, 'Umbrella Rig',
   'Trolling', 2, 0, 'SANDBOX TEST DATA #4 - skunked, too much rain', 'New Moon'),

  ('jcal0064@gmail.com', '2026-07-29', '05:45', '10:15', 4.5, 'Gills Creek',
   37.0655, -79.7102, 'Partly Cloudy', 78, 82, 'Gizzard Shad',
   'Trolling', 2, 0, 'SANDBOX TEST DATA #5 - best trip of the season', 'First Quarter');

-- Fish. Trip #4 deliberately gets none, so the "skunked" path has coverage.
insert into fish (session_id, species, length, weight, kept, depth)
select id, 'Striped Bass', 24.5, 5.2, 0, 22 from sessions where notes like 'SANDBOX TEST DATA #1%'
union all
select id, 'Striped Bass', 27.0, 7.1, 1, 25 from sessions where notes like 'SANDBOX TEST DATA #1%'
union all
select id, 'Striped Bass', 31.5, 11.4, 0, 34 from sessions where notes like 'SANDBOX TEST DATA #2%'
union all
select id, 'Striped Bass', 22.0, 4.0, 0, 18 from sessions where notes like 'SANDBOX TEST DATA #3%'
union all
select id, 'Striped Bass', 29.0, 8.8, 1, 20 from sessions where notes like 'SANDBOX TEST DATA #3%'
union all
select id, 'White Perch',   9.5, 0.6, 0, 15 from sessions where notes like 'SANDBOX TEST DATA #3%'
union all
select id, 'Striped Bass', 35.0, 16.2, 0, 28 from sessions where notes like 'SANDBOX TEST DATA #5%'
union all
select id, 'Striped Bass', 26.5, 6.9, 0, 30 from sessions where notes like 'SANDBOX TEST DATA #5%'
union all
select id, 'Striped Bass', 23.0, 4.6, 1, 26 from sessions where notes like 'SANDBOX TEST DATA #5%';

-- Spots. The first spot of each trip is the session's own lat/lon.
insert into spots (session_id, latitude, longitude, label, caught, fish_count)
select id, 37.0912, -79.6423, 'Bridge pilings', 1, 2 from sessions where notes like 'SANDBOX TEST DATA #1%'
union all
select id, 37.0934, -79.6470, 'North point',    0, 0 from sessions where notes like 'SANDBOX TEST DATA #1%'
union all
select id, 37.0488, -79.5761, 'Channel bend',   1, 1 from sessions where notes like 'SANDBOX TEST DATA #2%'
union all
select id, 37.1024, -79.6688, 'Creek mouth',    1, 3 from sessions where notes like 'SANDBOX TEST DATA #3%'
union all
select id, 37.0912, -79.6423, 'Bridge pilings', 0, 0 from sessions where notes like 'SANDBOX TEST DATA #4%'
union all
select id, 37.0655, -79.7102, 'Gills flat',     1, 3 from sessions where notes like 'SANDBOX TEST DATA #5%';

commit;

-- What you should get back: 5 trips, 9 fish, 6 spots.
select
  (select count(*) from sessions where notes like 'SANDBOX TEST DATA%') as trips,
  (select count(*) from fish  where session_id in (select id from sessions where notes like 'SANDBOX TEST DATA%')) as fish,
  (select count(*) from spots where session_id in (select id from sessions where notes like 'SANDBOX TEST DATA%')) as spots;
