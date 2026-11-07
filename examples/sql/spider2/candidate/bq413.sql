SELECT
  COALESCE(p.journal.title, p.proceedings_title.preferred, p.book_title.preferred, p.book_series_title.preferred) AS venue_title
FROM `bigquery-public-data.dimensions_ai_covid19.publications` AS p
WHERE p.date_inserted >= TIMESTAMP('2021-01-01')
  AND EXISTS (
    SELECT 1
    FROM UNNEST(p.authors) AS a
    CROSS JOIN UNNEST(a.affiliations_address) AS aa
    JOIN `bigquery-public-data.dimensions_ai_covid19.grid` AS g
      ON g.id = aa.grid_id
    WHERE g.address.city = 'Qianjiang'
  )