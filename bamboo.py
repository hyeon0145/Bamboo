import re

from urllib.parse import urljoin
from datetime import datetime, timedelta

from requests import Session
from bs4 import BeautifulSoup, NavigableString

def login_required(function):
    def inner(self, *args, **kwargs):
        if not self.is_logged_in:
            raise Exception('not logged in')
            
        return function(self, *args, **kwargs)
    
    return inner

class Bamboo:
    BASE_URL = 'https://bamboofo.rest'
    
    def __init__(self):
        self.session = Session()
        self.session.headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/51.0.2704.84 Safari/537.36'
        
        self.is_logged_in = False
        
    def login(self, email, password):
        if self.is_logged_in:
            raise Exception('already logged in')
            
        response = self.session.get(urljoin(Bamboo.BASE_URL, 'users/sign_in'))
        soup = BeautifulSoup(response.text, 'lxml')
        
        form = soup.find(id='new_user')

        parameters = {
            'utf8': form.select('input[name=utf8]')[0]['value'],
            'authenticity_token': form.select('input[name=authenticity_token]')[0]['value'],
            'user[email]': email,
            'user[password]': password,
        }
        
        response = self.session.post(urljoin(Bamboo.BASE_URL, 'users/sign_in'), data=parameters)
        if '<span id="flash_alert">아이디와 비밀번호를 확인해주세요</span>' in response.text:
            raise Exception('failed to login')
            
        self.is_logged_in = True

    @login_required
    def logout(self):
        self.session.get(urljoin(Bamboo.BASE_URL, 'users/sign_out'))
        self.is_logged_in = False
    
    @login_required
    def fetch_list(self, page=1, menu='f', topic=None):
        parameters = { 'page': page }
        if menu:
            parameters['m'] = menu
        if topic:
            parameters['t'] = topic

        response = self.session.get(urljoin('https://bamboofo.rest', 'posts'), params=parameters)
        soup = BeautifulSoup(response.text, 'lxml')
        
        return self._extract_list(soup)

    @login_required
    def fetch_item(self, identifier, menu=None, topic=None):

        parameters = dict()
        if menu:
            parameters['m'] = menu
        if topic:
            parameters['t'] = topic

        response = self.session.get(urljoin('https://bamboofo.rest', 'posts/{}'.format(identifier)), params=parameters)
        soup = BeautifulSoup(response.text, 'lxml')
        
        item = self._extract_item(soup)
        item['identifier'] = identifier

        return item
    
    def _extract_item(self, soup):
        def _extract_comments(soup):
            def _extract_upvote_downvote(element):
                match = re.match(r'\+(\d+)\s/\s\-(\d+)', element.text.strip())
                return tuple(map(int, match.groups()))
            
            items = []
            for element in soup.select('.comment'):
                if element.find(attrs={'class': 'deleted-comment'}):
                    continue
                
                item = {
                    'anchor': int(element.select('.comment-title .comment-anchor')[0].nextSibling.text.strip()[:-1]),
                    'author': element.find(attrs={'class': 'comment-name'}).text.strip(),
                    'content': element.find(attrs={'class': 'comment-content'}).text.strip(),
                    'published_date': self._parse_human_readable_date(element.select('.m-b-10 span')[4].text.strip()),
                }
                item['upvote'], item['downvote'] = _extract_upvote_downvote(soup.find(attrs={'class': 'time-recommend-info'}))
                
                items.append(item)
                
            return items
        
        def _extract_upvote_downvote_hit(element):
            match = re.match(r'\+(\d+)\s/\s\-(\d+)\s/\s조회\s(\d+)', element.text.strip())
            return tuple(map(int, match.groups()))
        
        item = {
            'topic': soup.select('.article-title-div .label')[0].text.strip(),
            'title': soup.find(id='post-title').text.strip(),
            'content': soup.find(id='content').text.strip(),
            'published_date': self._parse_human_readable_date(soup.select('.article-title-div .col-xs-8 .margin-left')[1].text.strip()),
            'comments': _extract_comments(soup),
        }
        item['upvote'], item['downvote'], item['hit'] = _extract_upvote_downvote_hit(soup.find(attrs={'class': 'time-recommend-info'}))
        
        return item
    
    def _extract_list(self, soup):
        def _extract_identifier(row):
            element = row.select('.post-table-title a')[0]
            match = re.match('/posts/(\d+)', element['href'].strip())

            return int(match.group(1))

        def _extract_topic(row):
            columns = row.find_all('td')

            return columns[2].text.strip()

        def _extract_title(row):
            element = row.find(attrs={'class': 'post-item-title' })

            blind_element = element.find(attrs={'class': 'blind' })
            if blind_element:
                return blind_element.text.strip()

            items = filter(lambda child: isinstance(child, NavigableString), element.children)
            return ' '.join(items).strip()

        def _extract_number_of_comments(row):
            element = row.find(attrs={'class': 'comment-count'})
            if not element:
                return 0

            match = re.match(r'\[(\d+)\]', element.text.strip())
            if not match:
                return 0

            return int(match.group(1))

        def _extract_upvote_downvote_hit(row):
            columns = row.find_all('td')

            match = re.match(r'\+(\d+)\s\-(\d+)\s/\s(\d+)', columns[4].text.strip())
            return tuple(map(int, match.groups()))

        def _extract_published_date(row):
            columns = row.find_all('td')
            element = columns[5]
            
            return self._parse_human_readable_date(element.text)
        
        items = []
        for row in soup.select('.post-table tbody tr'):
            if 'notice' in row['class']:
                continue
            
            item = {
                'identifier': _extract_identifier(row),
                'topic': _extract_topic(row),
                'title': _extract_title(row),
                'number_of_comments': _extract_number_of_comments(row),
                'published_date': _extract_published_date(row),
            }
            item['upvote'], item['downvote'], item['hit'] = _extract_upvote_downvote_hit(row)
            
            items.append(item)
            
        return items
    
    def _parse_human_readable_date(self, human_readable_date):
        timedelta_builder = {
            r'일초 전': lambda match: timedelta(seconds=1),
            r'(\d+)초 전': lambda match: timedelta(seconds=int(match.group(1))),
            r'일분 전': lambda match: timedelta(minutes=1),
            r'(\d+)분 전': lambda match: timedelta(minutes=int(match.group(1))),
            r'한시간 전': lambda match: timedelta(hours=1),
            r'(\d+)시간 전': lambda match: timedelta(hours=int(match.group(1))),
            r'하루 전': lambda match: timedelta(days=1),
            r'(\d+)일 전': lambda match: timedelta(days=int(match.group(1))),
            r'한달 전': lambda match: timedelta(days=1 * 30),
            r'(\d+)달 전': lambda match: timedelta(days=int(match.group(1)) * 30),
            r'일년 전': lambda match: timedelta(days=1 * 365),
            r'(\d+)년 전': lambda match: timedelta(days=int(match.group(1)) * 365),
        }
        
        for pattern, builder in timedelta_builder.items():
            match = re.match(pattern, human_readable_date.strip())
            if match:
                return datetime.now() - builder(match)

        return datetime.now()
