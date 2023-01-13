#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @Author       : BobAnkh
# @Github       : https://github.com/BobAnkh
# @Date         : 2020-08-06 10:48:37
# @LastEditTime : 2021-12-29 09:53:19
# @Description  : Main script of Github Action
# @Copyright 2020 BobAnkh

import argparse
import base64
import os
import re

import github
import yaml
from tqdm import tqdm

END_CHANGELOG_SIGNATURE = r'\* *This CHANGELOG was automatically generated by [auto-generate-changelog](https://github.com/BobAnkh/auto-generate-changelog)*'
BEGIN_CHANGELOG_TITLE = '# CHANGELOG'


def argument_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-m',
        '--mode',
        help=
        'choose to use local-dev mode or on github action mode. Valid values are \'local\' or \'github\'',
        default='github')
    parser.add_argument(
        '-f',
        '--file',
        help='configuration file to read from when running local-dev mode',
        default='.github/workflows/changelog.yml')
    parser.add_argument('-o',
                        '--output',
                        help='output file when running local-dev mode',
                        default='local-dev.md')
    parser.add_argument('-t', '--token', help='Github Access Token')
    args = parser.parse_args()
    return args


def set_local_env(env_name: str, env_value: str, prefix='INPUT'):
    '''
    set local env for dev

    Args:
        env_name (str): local env name.
        env_value (str): value of local env name.
        prefix (str, optional): prefix of env variable. Defaults to 'INPUT'.
    '''
    os.environ[prefix + '_{}'.format(env_name).upper()] = env_value


def get_inputs(input_name: str, prefix='INPUT') -> str:
    '''
    Get a Github actions input by name

    Args:
        input_name (str): input_name in workflow file.
        prefix (str, optional): prefix of input variable. Defaults to 'INPUT'.

    Returns:
        str: action_input

    References
    ----------
    [1] https://help.github.com/en/actions/automating-your-workflow-with-github-actions/metadata-syntax-for-github-actions#example
    '''
    return os.getenv(prefix + '_{}'.format(input_name).upper())


def set_env_from_file(file, args, prefix='INPUT'):
    '''
    Set env when use local-dev mode

    Args:
        file (str): path to config file
        args (object): argument
        prefix (str, optional): prefix of env. Defaults to 'INPUT'.
    '''
    f = open(file, encoding='utf-8')
    y = yaml.safe_load(f)
    for job in y['jobs'].values():
        for step in job['steps']:
            if re.match(r'BobAnkh/auto-generate-changelog', step['uses']):
                params = step['with']
                break
    option_params = [
        'REPO_NAME', 'ACCESS_TOKEN', 'PATH', 'COMMIT_MESSAGE', 'TYPE',
        'COMMITTER', 'DEFAULT_SCOPE', 'SUPPRESS_UNSCOPED'
    ]
    for param in option_params:
        if param not in params.keys():
            if param == 'ACCESS_TOKEN' and args.token:
                tmp = args.token
            else:
                tmp = input('Please input the value of ' + param + ':')
        elif param == 'ACCESS_TOKEN':
            if re.match(r'\$\{\{secrets\.', params[param]):
                if args.token:
                    tmp = args.token
                else:
                    tmp = input('Please input the value of ' + param + ':')
            else:
                tmp = params[param]
        elif param == 'REPO_NAME' and params[param] == '':
            tmp = input('Please input the value of ' + param + ':')
        else:
            tmp = params[param]
        set_local_env(param, tmp, prefix)


class GithubChangelog:
    '''
    Class for data interface of Github

    Use it to get changelog data and file content from Github and write new file content to Github
    '''

    def __init__(self, access_token: str, repo_name: str, path: str,
                 branch: str, pull_request: str, commit_message: str,
                 committer: str, unreleased_commits: bool,
                 regenerate_count: int, part_name, default_scope: str,
                 suppress_unscoped: bool, replace_empty_release_info: str):
        '''
        Initial GithubContributors

        Args:
            access_token (str): Personal Access Token for Github
            repo_name (str): The name of the repository
            path (str): The path to the file
            branch (str): The branch of the file
            pull_request (str): Pull request target branch, none means do not open a pull request
            commit_message (str): Commit message you want to use
            committer (str): Committer you want to use to commit the file
            unreleased_commits (bool): Whether to include unreleased commits in changelog
            regenerate_count (int): Regenerate recent n releases, 0 means only generate new releases, -1 means regenerate all releases
            part_name (list): a list of part_name, e.g. feat:Feature
            default_scope (str): scope which matches all un-scoped commits
            suppress_unscoped (bool): flag which suppresses entries for un-scoped commits
            replace_empty_release_info (str): replace empty release info with this string
        '''
        self.commit_message = commit_message
        self.path = path
        self.branch = branch
        self.pull_request = pull_request
        self.sha = ''
        self.releases = {}
        self.changelog = ''
        self.release_in_changelog = {}
        self.file_exists = False
        self.unreleased_commits = unreleased_commits
        self.regenerate_count = regenerate_count
        self.part_name = part_name
        self.default_scope = default_scope
        self.suppress_unscoped = suppress_unscoped
        self.replace_empty_release_info = replace_empty_release_info
        # Use PyGithub to login to the repository
        # References: https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository
        print('access token is ' + access_token)
        g = github.Github(access_token)
        self.repo = g.get_repo(repo_name)
        self.author = github.GithubObject.NotSet if committer == '' else github.InputGitAuthor(
            committer.split(' ')[0],
            committer.split(' ')[1])

    def get_data(self):
        '''
        Get data from Github to get/generate changelog for every releases
        '''
        # get file content
        self.get_exist_changelog()
        # get release info
        releases = self.repo.get_releases()
        regenerate_releases = [r.tag_name for r in releases]
        if self.regenerate_count < 0:
            pass
        else:
            regenerate_releases = regenerate_releases[0:self.regenerate_count]
        for r in releases:
            if r.tag_name not in self.release_in_changelog and r.tag_name not in regenerate_releases:
                regenerate_releases.append(r.tag_name)
        if self.unreleased_commits:
            regenerate_releases.append('Unreleased')
            self.releases['Unreleased'] = {
                'html_url': '',
                'body': '',
                'created_at': '',
                'commit_sha': '',
                'content': ''
            }
        print('[INFO] Regenerate releases:', regenerate_releases)
        # get tags
        tags = self.repo.get_tags()
        tags_sha = {}
        for tag in tags:
            tags_sha[tag.name] = tag.commit.sha
        # get all meta data for releases
        for release in releases:
            commit_sha = tags_sha[
                release.tag_name] if release.tag_name in tags_sha else ''
            release_content = self.release_in_changelog[
                release.
                tag_name] if release.tag_name in self.release_in_changelog and release.tag_name not in regenerate_releases else ''
            self.releases[release.tag_name] = {
                'html_url': release.html_url,
                'body': re.sub(r'\r\n', r'\n', release.body).strip('\n'),
                'created_at': release.created_at,
                'commit_sha': commit_sha,
                'content': release_content
            }
        release_commit_sha_list = {
            self.releases[x]['commit_sha']: x
            for x in self.releases
        }

        cur_release = 'Unreleased'
        # Get commits
        commits = self.get_github_commits()
        selected_commits = []
        if len(regenerate_releases) > 0:
            for commit in commits:
                if commit.sha in release_commit_sha_list:
                    if cur_release in regenerate_releases:
                        release_content, status_code = self.get_release_content(
                            cur_release, selected_commits)
                        if status_code != 0 and status_code != 200:
                            selected_commits = []
                            print(
                                "[ERROR] Failed to get release content, status code: "
                                + str(status_code))
                            break
                        self.releases[cur_release]['content'] = release_content
                        regenerate_releases.remove(cur_release)
                        cur_release = release_commit_sha_list[commit.sha]
                        if len(regenerate_releases) <= 0:
                            selected_commits = []
                            print(
                                "[INFO] All regenerate_releases are generated")
                            break
                    else:
                        cur_release = release_commit_sha_list[commit.sha]
                    selected_commits = [commit]
                else:
                    selected_commits.append(commit)
        if len(selected_commits) > 0 and cur_release in regenerate_releases:
            release_content, status_code = self.get_release_content(
                cur_release, selected_commits)
            if status_code != 0 and status_code != 200:
                selected_commits = []
                print("[ERROR] Failed to get release content, status code: " +
                      str(status_code))
            else:
                self.releases[cur_release]['content'] = release_content
                regenerate_releases.remove(cur_release)
        if len(regenerate_releases) > 0:
            print("[WARN] Failed to generate all the releases, left: " +
                  str(regenerate_releases))

    def get_exist_changelog(self):
        '''
        Get exist changelog from github and parse the exist releases in the changelog
        '''
        # get file content
        try:
            contents = self.repo.get_contents(self.path, self.branch)
        except github.GithubException as e:
            if e.status == 404:
                self.changelog = ''
            else:
                raise github.GithubException(e.status, e.data)
        else:
            self.file_exists = True
            self.path = contents.path
            self.sha = contents.sha
            base = contents.content
            base = base.replace('\n', '')
            self.changelog = base64.b64decode(base).decode('utf-8')
            self.analyze_changelog()

    def analyze_changelog(self): 
        # analyze changelog
        body_content = ''
        if self.changelog.startswith(
                BEGIN_CHANGELOG_TITLE) and self.changelog.endswith(
                    END_CHANGELOG_SIGNATURE + '\n'):
            body_content = self.changelog[len(BEGIN_CHANGELOG_TITLE
                                              ):-len(END_CHANGELOG_SIGNATURE +
                                                     '\n')]
        else:
            if self.changelog != '':
                print(
                    '\n[WARN] The changelog is not in the correct format! Will clear the changelog.'
                )
                return
        for release_body in body_content.split('\n\n## '):
            if release_body.startswith('Unreleased') or release_body == '':
                continue
            search_res = re.search(r'\[.*?\]', release_body)
            if search_res is None:
                print(
                    '[WARN] This part is not in the correct format! Will ignore this part.',
                    release_body.split('\n')[0])
                continue
            release_tag = search_res.group()[1:-1]
            self.release_in_changelog[
                release_tag] = '## ' + release_body.strip('\n')

    def get_github_commits(self):
        # Get commits
        try:
            commits = self.repo.get_commits(sha=self.branch)
            if commits.totalCount == 0:
                print('[WARN] No commits found on branch', self.branch)
                message = {}
                message['message'] = 'Not Found'
                message[
                    'documentation_url'] = 'https://docs.github.com/rest/commits/commits#list-commits'
                raise github.GithubException.UnknownObjectException(
                    404, message)
            return commits
        except github.GithubException as e:
            if e.status == 404:
                commits = self.repo.get_commits()
                if commits.totalCount == 0:
                    print('[WARN] No commits found on default branch')
                    message = {}
                    message['message'] = 'Not Found'
                    message[
                        'documentation_url'] = 'https://docs.github.com/rest/commits/commits#list-commits'
                    raise github.GithubException.UnknownObjectException(
                        404, message)
                return commits
            else:
                raise github.GithubException(e.status, e.data)

    def get_release_content(self, release_tag, commits):
        '''
        Get release content from processed commits
        '''
        selected_commits = []
        status_code = 0
        try:
            for commit in commits:
                message = commit.commit.message.split('\n\n')
                message_head = message[0]
                if message_head[-3:] == '...' and len(message) > 1:
                    if message[1][0:3] == '...':
                        message_head = re.sub(
                            r'  ', r' ', message_head[:-3] + ' ' +
                            message[1].split('\n')[0][3:])
                # TODO: #5 revert: remove from selected_commits
                url = commit.html_url
                pulls = commit.get_pulls()
                pr_links = []
                if pulls.totalCount == 0:
                    pass
                else:
                    for pull in pulls:
                        pr = f''' ([#{pull.number}]({pull.html_url}))'''
                        pr_links.append(pr)
                selected_commits.append({
                    'head': message_head,
                    'sha': commit.sha,
                    'url': url,
                    'pr_links': pr_links
                })
        except github.GithubException as e:
            if e.status == 403:
                status_code = e.status
                print("[ERROR] Failed to get release content, message:",
                      e.data)
                return '', status_code
            else:
                status_code = e.status
                print("[ERROR] Failed to get release content, message:",
                      e.data)
                return '', status_code
                # raise github.GithubException(e.status, e.data)
        else:
            release_content = generate_release_changelog(
                self.releases[release_tag], selected_commits, release_tag,
                self.part_name, self.default_scope, self.suppress_unscoped,
                self.replace_empty_release_info)
            return release_content, status_code

    def read_releases(self):
        return self.releases

    def assemble_changelog(self):
        '''
        Assemble the whole changelog from releases. Will not include the release if all things are empty.
        '''
        changelog = BEGIN_CHANGELOG_TITLE
        for release in self.releases.values():
            if release['content'] != '':
                changelog += '\n\n' + release['content'].strip('\n')
        changelog += '\n\n' + END_CHANGELOG_SIGNATURE + '\n'
        return changelog

    def write_data(self):
        changelog = self.assemble_changelog()
        if changelog == self.changelog:
            print(f'[WARN] Same changelog. Not push.')
        else:
            if self.file_exists:
                print(f'[INFO] Update changelog')
                print(self.path)
                print(self.commit_message)
                print(changelog)
                print(self.sha)
                print(self.branch)
                print(self.author)
                self.repo.update_file(self.path, self.commit_message,
                                      changelog, self.sha, self.branch,
                                      self.author)
            else:
                print(f'[INFO] Create changelog.')
                try:
                    self.repo.create_file(self.path, self.commit_message,
                                          changelog, self.branch, self.author)
                except github.GithubException as e:
                    if e.status == 404:
                        new_sha = self.repo.get_branch(
                            self.pull_request).commit.sha
                        self.repo.create_git_ref(f'refs/heads/{self.branch}',
                                                 new_sha)
                        # get file content
                        try:
                            contents = self.repo.get_contents(
                                self.path, self.branch)
                        except github.GithubException as e:
                            if e.status == 404:
                                self.repo.create_file(self.path,
                                                      self.commit_message,
                                                      changelog, self.branch,
                                                      self.author)
                            else:
                                raise github.GithubException(e.status, e.data)
                        else:
                            self.sha = contents.sha
                            self.repo.update_file(self.path,
                                                  self.commit_message,
                                                  changelog, self.sha,
                                                  self.branch, self.author)
                    else:
                        raise github.GithubException(e.status, e.data)

            print(
                f'[INFO] BRANCH: {self.branch}, PULL_REQUEST: {self.pull_request}'
            )
            if self.pull_request != '' and self.pull_request != self.branch:
                print(
                    f'[INFO] Create pull request from {self.branch} to {self.pull_request}'
                )
                self.repo.create_pull(title=self.commit_message,
                                      body=self.commit_message,
                                      base=self.pull_request,
                                      head=self.branch,
                                      draft=False,
                                      maintainer_can_modify=True)


def strip_commits(commits, type_regex, default_scope, suppress_unscoped):
    '''
    Bypass some commits

    Args:
        commits (list): list of commit(dict), whose keys are 'head', 'sha', 'url', 'pr_links'
        type_regex (string): regex expression to match.
        default_scope (str): scope which matches all un-scoped commits
        suppress_unscoped (bool): flag which suppresses entries for un-scoped commits

    Returns:
        dict: selected commits of every scope.
    '''
    # TODO: add an attribute to ignore scope
    regex = r'^' + type_regex + r'(?:[(](.+?)[)])?'
    scopes = {}
    for commit in commits:
        head = commit['head']
        if re.match(regex, head):
            scope = re.findall(regex, head)[0]
            if scope == '':
                if suppress_unscoped:
                    continue
                scope = default_scope
            if scope.lower(
            ) == 'changelog' and regex == r'^docs(?:[(](.+?)[)])?':
                continue
            subject = re.sub(regex + r'\s?:\s?', '', head)
            if scope in scopes:
                scopes[scope].append({'subject': subject, 'commit': commit})
            else:
                scopes[scope] = []
                scopes[scope].append({'subject': subject, 'commit': commit})
    return scopes


def generate_section(release_commits, regex, default_scope, suppress_unscoped):
    '''
    Generate scopes of a section

    Args:
        release_commits (dict): commits of the release
        regex (string): regex expression
        default_scope (str): scope which matches all un-scoped commits
        suppress_unscoped (bool): flag which suppresses entries for un-scoped commits

    Returns:
        string: content of section
    '''
    section = ''
    scopes = strip_commits(release_commits, regex, default_scope,
                           suppress_unscoped)
    for scope in scopes:
        scope_content = f'''- {scope}:\n'''
        for sel_commit in scopes[scope]:
            commit = sel_commit['commit']
            sha = commit['sha']
            url = commit['url']
            subject = sel_commit['subject']
            pr_links = commit['pr_links']
            scope_content = scope_content + f'''  - {subject} ([{sha[0:7]}]({url}))'''
            for pr_link in pr_links:
                scope_content = scope_content + pr_link
            scope_content = scope_content + '\n'
        section = section + scope_content + '\n'
    return section


def generate_release_body(release_commits, part_name, default_scope,
                          suppress_unscoped):
    '''
    Generate release body using part_name_dict and regex_list

    Args:
        release_commits (dict): commits of the release
        part_name (list): a list of part_name, e.g. feat:Feature
        default_scope (str): scope which matches all un-scoped commits
        suppress_unscoped (bool): flag which suppresses entries for un-scoped commits

    Returns:
        string: body part of release info
    '''
    release_body = ''
    # TODO: add a new attribute to ignore some commits with another new function
    for part in part_name:
        regex, name = part.split(':')
        sec = generate_section(release_commits, regex, default_scope,
                               suppress_unscoped)
        if sec != '':
            release_body = release_body + '### ' + name + '\n\n' + sec
    return release_body


def generate_release_changelog(meta_data, release_commits, release_tag,
                               part_name, default_scope, suppress_unscoped,
                               replace_empty_release_info):
    '''
    Generate CHANGELOG

    Args:
        meta_data (dict): release meta data
        release_commits (list): list of meta data of one release's commits
        release_tag (str): the corresponding release tag
        part_name (list): a list of part_name, e.g. feat:Feature
        default_scope (str): scope which matches all un-scoped commits
        suppress_unscoped (bool): flag which suppresses entries for un-scoped commits
        replace_empty_release_info (str): replace empty release info with this string

    Returns:
        string: content of one release's CHANGELOG
    '''
    release_info = ''
    if release_tag == 'Unreleased':
        title = 'Unreleased'
        description = replace_empty_release_info
        release_info = f'''## {title}\n\n{description}'''
    else:
        title = release_tag
        url = meta_data['html_url']
        origin_desc = re.split(
            r'<!-- HIDE IN CHANGELOG BEGIN -->(?:.|\n)*?<!-- HIDE IN CHANGELOG END -->',
            meta_data['body'])
        if len(origin_desc) == 1:
            description = origin_desc[0]
        else:
            description = ''
            for elem in origin_desc:
                if elem == origin_desc[0]:
                    para = re.sub(r'\n*$', r'', elem)
                    if para == '':
                        continue
                    elif description == '':
                        description = para.strip('\n')
                    else:
                        description = description.strip(
                            '\n') + '\n\n' + para.strip('\n')
                elif elem == origin_desc[-1]:
                    para = re.sub(r'^\n*', r'', elem)
                    if para == '':
                        continue
                    elif description == '':
                        description = para.strip('\n')
                    else:
                        description = description.strip(
                            '\n') + '\n\n' + para.strip('\n')
                else:
                    para = re.sub(r'\n*$', r'', elem)
                    para = re.sub(r'^\n*', r'', para)
                    if para == '':
                        continue
                    elif description == '':
                        description = para.strip('\n')
                    else:
                        description = description.strip(
                            '\n') + '\n\n' + para.strip('\n')
        date = meta_data['created_at']
        if description == '':
            description = replace_empty_release_info
        description = description.strip('\n')
        release_info = f'''## [{title}]({url}) - {date}\n\n{description}'''
    release_body = generate_release_body(release_commits, part_name,
                                         default_scope, suppress_unscoped)
    if release_body == '' and release_tag == 'Unreleased':
        changelog = ''
    else:
        changelog = release_info.strip('\n') + '\n\n' + release_body.strip(
            '\n')
    return changelog


def main():
    args = argument_parser()

    if args.mode == 'local':
        set_env_from_file(args.file, args)
    elif args.mode == 'github':
        pass
    else:
        print("Illegal mode option, please type \'-h\' to read the help")
        os.exit()

    ACCESS_TOKEN = get_inputs('ACCESS_TOKEN')
    REPO_NAME = get_inputs('REPO_NAME')
    if REPO_NAME == '':
        REPO_NAME = get_inputs('REPOSITORY', 'GITHUB')
    PATH = get_inputs('PATH')
    BRANCH = get_inputs('BRANCH')
    if BRANCH == '':
        BRANCH = github.GithubObject.NotSet
    PULL_REQUEST = get_inputs('PULL_REQUEST')
    COMMIT_MESSAGE = get_inputs('COMMIT_MESSAGE')
    COMMITTER = get_inputs('COMMITTER')
    part_name = re.split(r'\s?,\s?', get_inputs('TYPE'))
    DEFAULT_SCOPE = get_inputs('DEFAULT_SCOPE')
    SUPPRESS_UNSCOPED = get_inputs('SUPPRESS_UNSCOPED')
    UNRELEASED_COMMITS = get_inputs('UNRELEASED_COMMITS')
    REGENERATE_COUNT = int(get_inputs('REGENERATE_COUNT'))
    REPLACE_EMPTY_RELEASE_INFO = get_inputs('REPLACE_EMPTY_RELEASE_INFO')
    changelog = GithubChangelog(ACCESS_TOKEN, REPO_NAME, PATH, BRANCH,
                                PULL_REQUEST, COMMIT_MESSAGE, COMMITTER,
                                UNRELEASED_COMMITS == 'true', REGENERATE_COUNT,
                                part_name, DEFAULT_SCOPE,
                                SUPPRESS_UNSCOPED == 'true',
                                REPLACE_EMPTY_RELEASE_INFO)
    changelog.get_data()

    if args.mode == 'local':
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(changelog.assemble_changelog())
    else:
        changelog.write_data()


if __name__ == '__main__':
    main()
